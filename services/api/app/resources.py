"""Explicit staffed-room scheduling and snapshot-bound, human-approved calling."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from app.commands import CommandRoute
from app.database import get_db
from app.models import Room, StaffShift, ResourceBlock, ResourceAssignment, RoutingProposal, ServicePoint, ServiceEpisode, QueueEntry, User, QueueStateEvent, utcnow
from app.schemas import APIModel
from app.workspace_contracts import BoardResponse, ProposalResponse
from app.security import CurrentUser, require_roles, role_names
from app.access import allowed_services, service_action
from app.services.audit import record_audit, enqueue_event

router=APIRouter(prefix='/api/v1/operations',route_class=CommandRoute)
DB=Depends(get_db,scope='function')


class RoomInput(APIModel):
    service_point_id: uuid.UUID
    name: str = Field(min_length=3,max_length=80)


class IntervalInput(APIModel):
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode='after')
    def interval(self):
        if not self.starts_at.tzinfo or not self.ends_at.tzinfo or self.ends_at<=self.starts_at:
            raise ValueError('Use timezone-aware times with end after start')
        if self.ends_at-self.starts_at>timedelta(days=7): raise ValueError('Intervals are limited to seven days')
        return self


class ShiftInput(IntervalInput):
    staff_id: uuid.UUID
    room_id: uuid.UUID


class BlockInput(IntervalInput):
    room_id: uuid.UUID | None = None
    staff_id: uuid.UUID | None = None
    reason: str = Field(min_length=5,max_length=240)

    @model_validator(mode='after')
    def target(self):
        if bool(self.room_id)==bool(self.staff_id): raise ValueError('Choose one room or one staff member')
        return self


class VersionInput(APIModel):
    version: int = Field(ge=1)
    reason: str = Field(min_length=5,max_length=240)


class ProposalInput(APIModel):
    queue_entry_id: uuid.UUID
    version: int = Field(ge=1)


class ApprovalInput(APIModel):
    room_id: uuid.UUID
    reason: str = Field(min_length=5,max_length=240)


def scoped(db, model, ident, facility_id):
    obj=db.scalar(select(model).where(model.id==ident,model.facility_id==facility_id))
    if not obj: raise HTTPException(404,'Resource not found')
    return obj


def audit(db,user,action,obj,key,details=None,reason=None):
    record_audit(db,facility_id=user.facility_id,actor_id=user.id,action=action,object_type=type(obj).__name__,object_id=obj.id,
        correlation_id=key,new=details or {'changed':True},reason=reason)
    ref=getattr(obj,'service_point_id',None)
    if not ref and getattr(obj,'room_id',None): ref=db.get(Room,obj.room_id).service_point_id
    if not ref and getattr(obj,'episode_id',None): ref=db.get(ServiceEpisode,obj.episode_id).service_point_id
    enqueue_event(db,facility_id=user.facility_id,topic='service_point.capacity_changed',aggregate_id=ref or obj.id)


def room_snapshot(db, facility_id, point_id=None, at=None):
    at=at or utcnow()
    rooms=list(db.scalars(select(Room).where(Room.facility_id==facility_id).order_by(Room.name)))
    if point_id: rooms=[r for r in rooms if r.service_point_id==point_id]
    shifts=list(db.scalars(select(StaffShift).where(StaffShift.facility_id==facility_id,StaffShift.cancelled.is_(False),StaffShift.starts_at<=at,StaffShift.ends_at>at)))
    blocks=list(db.scalars(select(ResourceBlock).where(ResourceBlock.facility_id==facility_id,ResourceBlock.cancelled.is_(False),ResourceBlock.starts_at<=at,ResourceBlock.ends_at>at)))
    allocations=list(db.scalars(select(ResourceAssignment).where(ResourceAssignment.facility_id==facility_id,ResourceAssignment.released_at.is_(None))))
    rows=[]
    for room in rooms:
        point=db.get(ServicePoint,room.service_point_id)
        shift=next((s for s in shifts if s.room_id==room.id),None)
        staff=db.get(User,shift.staff_id) if shift else None
        reasons=[]
        if not room.enabled or not point.active or point.capacity<=0 or point.outage_state=='UNAVAILABLE': reasons.append('Room or service unavailable')
        if not staff or not staff.active: reasons.append('No active on-duty staff')
        if staff:
            try: service_action(staff,SimpleNamespace(service_point=point))
            except HTTPException: reasons.append('Staff no longer authorised for service')
        if any(b.room_id==room.id or (staff and b.staff_id==staff.id) for b in blocks): reasons.append('Scheduled break or outage')
        staffed=not reasons
        assignment=next((a for a in allocations if a.room_id==room.id or (staff and a.staff_id==staff.id)),None)
        if assignment: reasons.append('Reserved or in service; current work is preserved')
        rows.append({'id':str(room.id),'name':room.name,'service_point_id':str(point.id),'service_type':point.type,'version':room.version,
            'staff_id':str(staff.id) if staff else None,'staff_name':staff.display_name if staff else None,
            'available':not reasons,'staffed':staffed,'reasons':reasons,'shift_id':str(shift.id) if shift else None,
            'assignment_id':str(assignment.id) if assignment else None,'episode_id':str(assignment.episode_id) if assignment else None})
    return rows


def snapshot_hash(rows):
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()


def has_rooms(db, point_id):
    return db.scalar(select(Room.id).where(Room.service_point_id==point_id).limit(1)) is not None


def guard_reservation(db, episode, starting=False):
    if not has_rooms(db,episode.service_point_id): return
    assignment=db.scalar(select(ResourceAssignment).where(ResourceAssignment.episode_id==episode.id,ResourceAssignment.released_at.is_(None)))
    if not assignment: raise HTTPException(409,'Request and approve a staffed-room assignment in Operations before calling')
    if starting and not assignment.started_at:
        # An approved reservation cannot start through a subsequent break/outage.
        state=next(r for r in room_snapshot(db,episode.facility_id,episode.service_point_id) if r['id']==str(assignment.room_id))
        if state['staff_id']!=str(assignment.staff_id) or any('Reserved' not in reason for reason in state['reasons']):
            raise HTTPException(409,'Assigned staff/room unavailable; preserve the call or cancel and requeue explicitly')
        assignment.started_at=utcnow()


def release_assignment(db,episode):
    assignment=db.scalar(select(ResourceAssignment).where(ResourceAssignment.episode_id==episode.id,ResourceAssignment.released_at.is_(None)))
    if assignment: assignment.released_at=utcnow()


def utilisation(db,facility_id,start,end):
    """Integrate recorded staffed intervals minus blocks; preserve busy overruns."""
    rooms=list(db.scalars(select(Room).where(Room.facility_id==facility_id)))
    shifts=list(db.scalars(select(StaffShift).where(StaffShift.facility_id==facility_id,StaffShift.cancelled.is_(False),StaffShift.ends_at>start,StaffShift.starts_at<end)))
    blocks=list(db.scalars(select(ResourceBlock).where(ResourceBlock.facility_id==facility_id,ResourceBlock.cancelled.is_(False),ResourceBlock.ends_at>start,ResourceBlock.starts_at<end)))
    assignments=list(db.scalars(select(ResourceAssignment).where(ResourceAssignment.facility_id==facility_id,ResourceAssignment.started_at.is_not(None),ResourceAssignment.started_at<end)))
    result=[]
    for room in rooms:
        available=busy=0.
        for shift in [s for s in shifts if s.room_id==room.id]:
            lo=max(start,shift.starts_at,shift.created_at);hi=min(end,shift.ends_at)
            if hi<=lo: continue
            relevant=[b for b in blocks if b.room_id==room.id or b.staff_id==shift.staff_id]
            cuts=sorted({lo,hi,*[max(lo,min(hi,t)) for b in relevant for t in [max(b.starts_at,b.created_at),b.ends_at]]})
            for a,b in zip(cuts,cuts[1:]):
                midpoint=a+(b-a)/2
                if not any(max(x.starts_at,x.created_at)<=midpoint<x.ends_at for x in relevant): available+=(b-a).total_seconds()/60
        for a in [a for a in assignments if a.room_id==room.id]:
            busy+=max(0,(min(end,a.released_at or end)-max(start,a.started_at)).total_seconds()/60)
        result.append({'room':room.name,'available_minutes':round(available,3),'occupied_minutes':round(busy,3),
            'utilisation':busy/available if available else None})
    return {'from':start,'through':end,'rooms':result,'definition':'Occupied minutes / recorded scheduled staffed-room minutes minus recorded breaks/outages. Pauses reserve the room. Existing service may overrun an outage, so the ratio can exceed 1.',
        'limitation':'Schedules are recorded operational availability, not independently observed physical attendance; no history before record creation is inferred.'}


@router.get('/board',response_model=BoardResponse)
def board(user=Depends(require_roles('ADMIN','MANAGER','CLINICIAN','TRIAGE_NURSE','SERVICE_PROVIDER','PHARMACY')),db:Session=DB):
    privileged=bool(role_names(user)&{'ADMIN','MANAGER'})
    rooms=[r for r in room_snapshot(db,user.facility_id) if privileged or r['service_type'] in allowed_services(user)]
    room_ids=[uuid.UUID(r['id']) for r in rooms]
    staff=list(db.scalars(select(User).where(User.facility_id==user.facility_id,User.active.is_(True))))
    return {'rooms':rooms,'staff':[{'id':str(u.id),'name':u.display_name,'roles':sorted(role_names(u))} for u in staff if role_names(u)&{'CLINICIAN','TRIAGE_NURSE','SERVICE_PROVIDER','PHARMACY'}],
        'shifts':[{'id':str(s.id),'staff_id':str(s.staff_id),'room_id':str(s.room_id),'starts_at':s.starts_at,'ends_at':s.ends_at,'cancelled':s.cancelled,'version':s.version} for s in db.scalars(select(StaffShift).where(StaffShift.facility_id==user.facility_id,StaffShift.room_id.in_(room_ids)).order_by(StaffShift.starts_at.desc()).limit(150))],
        'blocks':[{'id':str(b.id),'room_id':str(b.room_id) if b.room_id else None,'staff_id':str(b.staff_id) if b.staff_id else None,'starts_at':b.starts_at,'ends_at':b.ends_at,'reason':b.reason,'cancelled':b.cancelled,'version':b.version} for b in db.scalars(select(ResourceBlock).where(ResourceBlock.facility_id==user.facility_id).order_by(ResourceBlock.starts_at.desc()).limit(150))],
        'history':utilisation(db,user.facility_id,utcnow()-timedelta(days=1),utcnow()) if privileged else None}


@router.post('/rooms',status_code=201)
def create_room(payload:RoomInput,user=Depends(require_roles('ADMIN','MANAGER')),db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    scoped(db,ServicePoint,payload.service_point_id,user.facility_id)
    if db.scalar(select(ServiceEpisode.id).where(ServiceEpisode.service_point_id==payload.service_point_id,ServiceEpisode.status.in_(['CALLED','IN_SERVICE','PAUSED'])).limit(1)):
        raise HTTPException(409,'Finish existing unassigned calls before configuring staffed rooms')
    room=Room(facility_id=user.facility_id,**payload.model_dump());db.add(room);db.flush();audit(db,user,'room.created',room,key)
    return {'id':str(room.id),'version':room.version}


@router.post('/shifts',status_code=201)
def create_shift(payload:ShiftInput,user=Depends(require_roles('ADMIN','MANAGER')),db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    room=scoped(db,Room,payload.room_id,user.facility_id);staff=scoped(db,User,payload.staff_id,user.facility_id)
    if not staff.active: raise HTTPException(422,'Staff account is disabled')
    service_action(staff,SimpleNamespace(service_point=db.get(ServicePoint,room.service_point_id)))
    collision=db.scalar(select(StaffShift.id).where(StaffShift.facility_id==user.facility_id,StaffShift.cancelled.is_(False),
        or_(StaffShift.staff_id==staff.id,StaffShift.room_id==room.id),StaffShift.starts_at<payload.ends_at,StaffShift.ends_at>payload.starts_at).limit(1))
    if collision: raise HTTPException(409,'Staff or room already has an overlapping shift')
    shift=StaffShift(facility_id=user.facility_id,**payload.model_dump());db.add(shift);db.flush();audit(db,user,'shift.created',shift,key)
    return {'id':str(shift.id),'version':shift.version}


@router.post('/blocks',status_code=201)
def create_block(payload:BlockInput,user=Depends(require_roles('ADMIN','MANAGER')),db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    scoped(db,Room if payload.room_id else User,payload.room_id or payload.staff_id,user.facility_id)
    block=ResourceBlock(facility_id=user.facility_id,**payload.model_dump());db.add(block);db.flush();audit(db,user,'resource.blocked',block,key,reason=payload.reason)
    return {'id':str(block.id),'version':block.version,'in_progress_service_interrupted':False}


@router.post('/schedule/{kind}/{record_id}/cancel')
def cancel(kind:str,record_id:uuid.UUID,payload:VersionInput,user=Depends(require_roles('ADMIN','MANAGER')),db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    if kind not in {'shifts','blocks'}: raise HTTPException(404,'Schedule not found')
    obj=scoped(db,StaffShift if kind=='shifts' else ResourceBlock,record_id,user.facility_id)
    if obj.version!=payload.version or obj.cancelled or obj.starts_at<=utcnow(): raise HTTPException(409,'Only unchanged future schedule entries may be cancelled; history is preserved')
    obj.cancelled=True;obj.version+=1;audit(db,user,'schedule.cancelled',obj,key,reason=payload.reason)
    return {'cancelled':True,'version':obj.version}


@router.post('/proposals',status_code=201,response_model=ProposalResponse)
def propose(payload:ProposalInput,user:CurrentUser,db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    from app.services.queue import rank_queue
    from app.operational_prediction import estimate_duration
    entry=scoped(db,QueueEntry,payload.queue_entry_id,user.facility_id);service_action(user,entry.episode)
    eligible=rank_queue(db,user.facility_id,entry.service_point_id)
    if not eligible or eligible[0]['queue_entry_id']!=str(entry.id) or entry.version!=payload.version:
        raise HTTPException(409,'Only the current clinician-approved queue head may be assigned; refresh or record a clinician override')
    rows=room_snapshot(db,user.facility_id,entry.service_point_id)
    if not rows: raise HTTPException(409,'Configure rooms and shifts before resource-aware assignment')
    recent=list(db.scalars(select(ResourceAssignment).where(ResourceAssignment.facility_id==user.facility_id,ResourceAssignment.approved_at>=utcnow()-timedelta(hours=8))))
    loads={r['id']:sum(str(a.room_id)==r['id'] for a in recent) for r in rows}
    # Population room-occupancy estimates, never this patient's duration or urgency.
    history=list(db.scalars(select(ResourceAssignment).where(ResourceAssignment.facility_id==user.facility_id,
        ResourceAssignment.started_at.is_not(None),ResourceAssignment.released_at.is_not(None),ResourceAssignment.approved_at>=utcnow()-timedelta(days=30))))
    samples={r['id']:[(a.released_at-a.started_at).total_seconds()/60 for a in history if str(a.room_id)==r['id'] and a.released_at>a.started_at] for r in rows}
    calibrated=all(len(samples[r['id']])>=5 for r in rows if r['available'])
    means={r['id']:sum(samples[r['id']])/len(samples[r['id']]) if samples[r['id']] else None for r in rows}
    ready=sorted((r for r in rows if r['available']),key=lambda r:(means[r['id']] if calibrated else 0,loads[r['id']],r['name']))
    basis='Lowest mean occupied duration among available compatible rooms; descriptive history, not a causal staff-performance ranking' if calibrated else 'Insufficient comparable room history; least assigned available room in the last 8 hours is a transparent fallback'
    options=[{**r,'recent_assignments':loads[r['id']],'room_history_samples':len(samples[r['id']]),'mean_occupied_minutes':means[r['id']],
        'explanation':(f"{basis}. {loads[r['id']]} recent assignments. Patient priority is unchanged." if r['available'] else '; '.join(r['reasons']))} for r in rows]
    duration=estimate_duration(db,entry.episode)
    proposal=RoutingProposal(facility_id=user.facility_id,episode_id=entry.episode_id,actor_id=user.id,queue_version=entry.version,
        snapshot_hash=snapshot_hash(rows),options_json=options)
    db.add(proposal);db.flush();audit(db,user,'routing.proposed',proposal,key)
    return {'id':str(proposal.id),'options':options,'recommended_room_id':ready[0]['id'] if ready else None,'duration_estimate':duration,'expires_at':proposal.created_at+timedelta(minutes=5),'requires_approval':True}


@router.post('/proposals/{proposal_id}/approve')
def approve(proposal_id:uuid.UUID,payload:ApprovalInput,user:CurrentUser,db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    from app.services.queue import rank_queue, atomic_call
    from app.operational_prediction import estimate_duration
    proposal=scoped(db,RoutingProposal,proposal_id,user.facility_id)
    episode=scoped(db,ServiceEpisode,proposal.episode_id,user.facility_id);service_action(user,episode)
    entry=episode.queue_entry
    rows=room_snapshot(db,user.facility_id,episode.service_point_id)
    if proposal.status!='PENDING' or proposal.created_at<utcnow()-timedelta(minutes=5) or snapshot_hash(rows)!=proposal.snapshot_hash:
        raise HTTPException(409,'Proposal expired or resources changed; request a fresh proposal')
    rank=rank_queue(db,user.facility_id,episode.service_point_id)
    if not rank or rank[0]['queue_entry_id']!=str(entry.id) or entry.version!=proposal.queue_version: raise HTTPException(409,'Queue changed; refresh before approving')
    selected=next((r for r in rows if r['id']==str(payload.room_id) and r['available']),None)
    if not selected: raise HTTPException(409,'Chosen room is not currently compatible and available')
    assignment=ResourceAssignment(facility_id=user.facility_id,episode_id=episode.id,room_id=payload.room_id,staff_id=uuid.UUID(selected['staff_id']),approved_by=user.id,prediction_json=estimate_duration(db,episode))
    db.add(assignment);db.flush()
    atomic_call(db,entry,user.id,proposal.queue_version)
    db.add(QueueStateEvent(facility_id=user.facility_id,episode_id=episode.id,actor_id=user.id,from_status='WAITING',to_status='CALLED'))
    proposal.status='APPROVED';proposal.chosen_room_id=payload.room_id;proposal.reason=payload.reason
    audit(db,user,'routing.approved_and_called',proposal,key,details={'room_id':str(payload.room_id),'assignment_id':str(assignment.id)},reason=payload.reason)
    enqueue_event(db,facility_id=user.facility_id,topic='episode.called',aggregate_id=episode.id)
    return {'assignment_id':str(assignment.id),'status':'CALLED','priority_changed':False,'room':selected['name']}
