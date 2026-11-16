"""Role-scoped longitudinal workspace, structured observations and handovers."""
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.commands import CommandRoute
from app.database import get_db
from app.models import Patient, Visit, ServicePoint, Observation, EncounterNote, Handover, TriageAssessment, utcnow
from app.schemas import APIModel
from app.workspace_contracts import ObservationFieldResponse, WorkspaceResponse, HandoverResponse, NoteResponse
from app.security import CurrentUser, require_roles, role_names
from app.access import allowed_services, service_action
from app.services.workflow import require_visit, require_episode
from app.services.audit import record_audit, enqueue_event

router=APIRouter(prefix='/api/v1',route_class=CommandRoute)
DB=Depends(get_db,scope='function')
# Units are recording metadata, not clinical normal ranges or triage thresholds.
FIELDS={'temperature':('Temperature','°C'),'pulse':('Pulse','beats/min'),
        'respiratory_rate':('Respiratory rate','breaths/min'),'oxygen_saturation':('Oxygen saturation','%'),
        'systolic_pressure':('Systolic pressure','mmHg'),'diastolic_pressure':('Diastolic pressure','mmHg')}


class ObservationInput(APIModel):
    field_code: Literal['temperature','pulse','respiratory_rate','oxygen_saturation','systolic_pressure','diastolic_pressure']
    value: float | None = None


class ObservationsInput(APIModel):
    observations: list[ObservationInput] = Field(min_length=1,max_length=6)


class NoteInput(APIModel):
    text: str = Field(min_length=3,max_length=1000)


class HandoverInput(APIModel):
    target_point_id: uuid.UUID
    message: str = Field(min_length=3,max_length=1000)


class VersionInput(APIModel):
    version: int = Field(ge=1)


@router.get('/observation-fields',response_model=list[ObservationFieldResponse])
def observation_fields(user: CurrentUser):
    return [{'code':k,'label':v[0],'unit':v[1],'required':False} for k,v in FIELDS.items()]


@router.get('/patients/{patient_id}/workspace',response_model=WorkspaceResponse)
def workspace(patient_id: uuid.UUID,user=Depends(require_roles('RECEPTIONIST','CLINICIAN','TRIAGE_NURSE')),db:Session=DB):
    from app.main import visit_view
    patient=db.scalar(select(Patient).where(Patient.id==patient_id,Patient.facility_id==user.facility_id))
    if not patient: raise HTTPException(404,'Patient not found')
    visits=db.scalars(select(Visit).where(Visit.patient_id==patient.id,Visit.facility_id==user.facility_id).order_by(Visit.arrival_at.desc())).all()
    clinical=bool(role_names(user)&{'CLINICIAN','TRIAGE_NURSE'})
    items=[]
    for visit in visits:
        item=visit_view(visit)
        item['observations']=[];item['notes']=[];item['assessments']=[];item['handovers']=[]
        if clinical:
            item['observations']=[{'id':str(o.id),'field_code':o.field_code,'value':o.value,'unit':o.unit,'observed_at':o.observed_at} for o in db.scalars(select(Observation).where(Observation.visit_id==visit.id,Observation.facility_id==user.facility_id).order_by(Observation.observed_at))]
            item['assessments']=[{'urgency':a.configured_urgency,'reason':a.reason,'at':a.assessed_at} for a in db.scalars(select(TriageAssessment).where(TriageAssessment.visit_id==visit.id).order_by(TriageAssessment.assessed_at))]
            eps=[e.id for e in visit.episodes]
            item['notes']=[{'id':str(n.id),'episode_id':str(n.episode_id),'text':n.text,'at':n.created_at} for n in db.scalars(select(EncounterNote).where(EncounterNote.facility_id==user.facility_id,EncounterNote.episode_id.in_(eps)).order_by(EncounterNote.created_at))]
            item['handovers']=[handover_view(h) for h in db.scalars(select(Handover).where(Handover.visit_id==visit.id,Handover.facility_id==user.facility_id).order_by(Handover.created_at))]
        items.append(item)
    return {'patient':{'id':str(patient.id),'pseudonym':patient.pseudonym,'age_band':patient.age_band,'sex':patient.sex,'synthetic':patient.synthetic_flag},'visits':items,'clinical_details_visible':clinical}


def handover_view(h):
    return {'id':str(h.id),'visit_id':str(h.visit_id),'source_episode_id':str(h.source_episode_id),'target_point_id':str(h.target_point_id),
        'message':h.message,'acknowledged_at':h.acknowledged_at,'version':h.version,'created_at':h.created_at}


def evidence(db,user,action,ref,key):
    record_audit(db,facility_id=user.facility_id,actor_id=user.id,action=action,object_type='Workspace',object_id=ref,correlation_id=key,new={'recorded':True})
    enqueue_event(db,facility_id=user.facility_id,topic='visit.state_changed',aggregate_id=ref)


@router.post('/visits/{visit_id}/observations',status_code=201)
def observations(visit_id:uuid.UUID,payload:ObservationsInput,user=Depends(require_roles('CLINICIAN','TRIAGE_NURSE')),db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    visit=require_visit(db,visit_id,user.facility_id)
    if visit.status not in {'AWAITING_TRIAGE','ACTIVE','ESCALATION_REQUIRED'}: raise HTTPException(409,'Observations require an active encounter')
    if len({o.field_code for o in payload.observations})!=len(payload.observations): raise HTTPException(422,'Each field may appear only once')
    from app.advisory import check_recording_ranges
    problems=check_recording_ranges({o.field_code:o.value for o in payload.observations})
    if problems: raise HTTPException(422,'; '.join(problems))
    for o in payload.observations:
        db.add(Observation(facility_id=user.facility_id,visit_id=visit.id,field_code=o.field_code,value=None if o.value is None else str(o.value),unit=FIELDS[o.field_code][1],entered_by=user.id))
    evidence(db,user,'observations.recorded',visit.id,key)
    return {'recorded':len(payload.observations),'priority_changed':False}


@router.post('/episodes/{episode_id}/notes',status_code=201)
def note(episode_id:uuid.UUID,payload:NoteInput,user:CurrentUser,db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    ep=require_episode(db,episode_id,user.facility_id);service_action(user,ep)
    n=EncounterNote(facility_id=user.facility_id,episode_id=ep.id,actor_id=user.id,text=payload.text)
    db.add(n);db.flush();evidence(db,user,'encounter.note_added',ep.visit_id,key)
    return {'id':str(n.id),'recorded':True}


@router.get('/episodes/{episode_id}/notes',response_model=list[NoteResponse])
def episode_notes(episode_id:uuid.UUID,user:CurrentUser,db:Session=DB):
    ep=require_episode(db,episode_id,user.facility_id);service_action(user,ep)
    return [{'id':str(n.id),'episode_id':str(n.episode_id),'text':n.text,'at':n.created_at} for n in db.scalars(select(EncounterNote).where(EncounterNote.episode_id==ep.id,EncounterNote.facility_id==user.facility_id).order_by(EncounterNote.created_at))]


@router.post('/episodes/{episode_id}/handovers',status_code=201,response_model=HandoverResponse)
def handover(episode_id:uuid.UUID,payload:HandoverInput,user:CurrentUser,db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    ep=require_episode(db,episode_id,user.facility_id);service_action(user,ep)
    point=db.scalar(select(ServicePoint).where(ServicePoint.id==payload.target_point_id,ServicePoint.facility_id==user.facility_id,ServicePoint.active.is_(True)))
    if not point or point.type not in ep.service_point.allowed_routes: raise HTTPException(422,'Handover target must be a configured permitted route')
    h=Handover(facility_id=user.facility_id,visit_id=ep.visit_id,source_episode_id=ep.id,target_point_id=point.id,actor_id=user.id,message=payload.message)
    db.add(h);db.flush();evidence(db,user,'handover.created',ep.visit_id,key)
    return handover_view(h)


@router.get('/handovers',response_model=list[HandoverResponse])
def handovers(user=Depends(require_roles('CLINICIAN','TRIAGE_NURSE','SERVICE_PROVIDER','PHARMACY')),db:Session=DB):
    points=list(db.scalars(select(ServicePoint.id).where(ServicePoint.facility_id==user.facility_id,ServicePoint.type.in_(allowed_services(user)))))
    return [handover_view(h) for h in db.scalars(select(Handover).where(Handover.facility_id==user.facility_id,Handover.target_point_id.in_(points),Handover.acknowledged_at.is_(None)).order_by(Handover.created_at).limit(100))]


@router.post('/handovers/{handover_id}/acknowledge',response_model=HandoverResponse)
def acknowledge(handover_id:uuid.UUID,payload:VersionInput,user=Depends(require_roles('CLINICIAN','TRIAGE_NURSE','SERVICE_PROVIDER','PHARMACY')),db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    h=db.scalar(select(Handover).where(Handover.id==handover_id,Handover.facility_id==user.facility_id))
    if not h: raise HTTPException(404,'Handover not found')
    point=db.get(ServicePoint,h.target_point_id)
    # Reuse action permission rather than the broader read permission.
    from types import SimpleNamespace
    service_action(user,SimpleNamespace(service_point=point))
    if h.version!=payload.version or h.acknowledged_at: raise HTTPException(409,'Handover changed; refresh')
    h.acknowledged_by=user.id;h.acknowledged_at=utcnow();h.version+=1
    evidence(db,user,'handover.acknowledged',h.visit_id,key)
    return handover_view(h)
