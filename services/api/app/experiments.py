import csv
import hashlib
import io
import json
import uuid
from datetime import datetime
from typing import Any
from fastapi import APIRouter,Depends,Header,HTTPException,Response
from pydantic import Field,model_validator
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.commands import CommandRoute
from app.database import get_db
from app.models import ExperimentScenarioVersion,ExperimentRun,Job
from app.schemas import APIModel
from app.security import require_roles,rate_limiter
from app.services.audit import record_audit

router=APIRouter(prefix='/api/v1/experiments',route_class=CommandRoute)
DB=Depends(get_db,scope='function')
RESEARCH=Depends(require_roles('ADMIN','MANAGER','RESEARCHER'))


class Block(APIModel):
    room:int=Field(ge=0,le=5)
    start:float=Field(ge=0,le=1440)
    duration:float=Field(gt=0,le=720)
    kind:str=Field(pattern='^(STAFF_BREAK|ROOM_OUTAGE)$')


class ExperimentConfig(APIModel):
    seed:int=Field(default=2026,ge=0,le=1000000000)
    patients:int=Field(default=50,ge=10,le=400)
    replications:int=Field(default=5,ge=1,le=20)
    rooms:int=Field(default=3,ge=1,le=6)
    arrivals_per_hour:float=Field(default=24,gt=0,le=150)
    mean_service_minutes:float=Field(default=12,gt=0,le=120)
    service_tail:float=Field(default=.5,ge=.1,le=1.5)
    horizon_minutes:float=Field(default=480,ge=60,le=1440)
    laboratory_probability:float=Field(default=.3,ge=0,le=1)
    no_show_probability:float=Field(default=.12,ge=0,le=1)
    return_delay_minutes:float=Field(default=15,ge=1,le=120)
    room_speed_factors:list[float]=Field(default_factory=lambda:[1.5,.7,1.],min_length=1,max_length=6)
    room_shifts:list[tuple[float,float]]=Field(default_factory=lambda:[(0,480),(0,480),(30,480)],min_length=1,max_length=6)
    blocks:list[Block]=Field(default_factory=lambda:[Block(room=0,start=45,duration=20,kind='STAFF_BREAK'),Block(room=1,start=60,duration=35,kind='ROOM_OUTAGE')],max_length=20)
    demand_multipliers:list[float]=Field(default_factory=lambda:[.75,1.,1.25],min_length=1,max_length=3)

    @model_validator(mode='after')
    def configuration(self):
        if len(self.room_speed_factors)!=self.rooms or len(self.room_shifts)!=self.rooms: raise ValueError('Supply one speed factor and shift per room')
        if any(not .25<=v<=4 for v in self.room_speed_factors): raise ValueError('Room speed factors must be between .25 and 4')
        if any(not 0<=a<b<=self.horizon_minutes for a,b in self.room_shifts): raise ValueError('Room shifts must fit within the observation horizon')
        if any(b.room>=self.rooms or b.start+b.duration>self.horizon_minutes for b in self.blocks): raise ValueError('Blocks must reference a configured room and fit the horizon')
        if 1. not in self.demand_multipliers or len(set(self.demand_multipliers))!=len(self.demand_multipliers) or any(not .25<=v<=3 for v in self.demand_multipliers): raise ValueError('Distinct demand multipliers between .25 and 3 must include 1')
        return self


class ScenarioInput(APIModel):
    name:str=Field(min_length=3,max_length=120)
    rationale:str=Field(min_length=5,max_length=500)
    series_id:uuid.UUID|None=None
    previous_revision:int|None=Field(default=None,ge=1)
    config:ExperimentConfig=Field(default_factory=ExperimentConfig)


class ScenarioResponse(APIModel):
    id:str
    series_id:str
    revision:int
    name:str
    config:ExperimentConfig
    config_hash:str
    rationale:str
    created_at:datetime


class RunSummary(APIModel):
    id:str
    scenario_version_id:str
    status:str
    created_at:datetime


class RunResponse(APIModel):
    id:str
    scenario_version_id:str
    status:str
    # Historical reports retain their engine-versioned schema and full provenance.
    results:dict[str,Any]


def view(s):
    return {'id':str(s.id),'series_id':str(s.series_id),'revision':s.revision,'name':s.name,'config':s.config_json,'config_hash':s.config_hash,'rationale':s.rationale,'created_at':s.created_at}


@router.get('/scenarios',response_model=list[ScenarioResponse])
def scenarios(user=RESEARCH,db:Session=DB):
    return [view(s) for s in db.scalars(select(ExperimentScenarioVersion).where(ExperimentScenarioVersion.facility_id==user.facility_id).order_by(ExperimentScenarioVersion.created_at.desc()).limit(100))]


@router.post('/scenarios',status_code=201,response_model=ScenarioResponse)
def create(payload:ScenarioInput,user=RESEARCH,db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    revision=1;series=payload.series_id or uuid.uuid4()
    if payload.series_id:
        last=db.scalar(select(func.max(ExperimentScenarioVersion.revision)).where(ExperimentScenarioVersion.facility_id==user.facility_id,ExperimentScenarioVersion.series_id==series))
        if not last: raise HTTPException(404,'Scenario series not found')
        if payload.previous_revision!=last: raise HTTPException(409,'Scenario revision changed; refresh before creating a version')
        revision=last+1
    config=payload.config.model_dump(mode='json')
    s=ExperimentScenarioVersion(facility_id=user.facility_id,series_id=series,revision=revision,name=payload.name,rationale=payload.rationale,
        config_json=config,config_hash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),actor_id=user.id)
    db.add(s);db.flush();record_audit(db,facility_id=user.facility_id,actor_id=user.id,action='experiment.scenario_versioned',object_type='ExperimentScenarioVersion',object_id=s.id,correlation_id=key,new={'revision':revision,'config_hash':s.config_hash})
    return view(s)


@router.post('/scenarios/{scenario_id}/run',status_code=202)
def run(scenario_id:uuid.UUID,user=RESEARCH,db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    s=db.scalar(select(ExperimentScenarioVersion).where(ExperimentScenarioVersion.id==scenario_id,ExperimentScenarioVersion.facility_id==user.facility_id))
    if not s: raise HTTPException(404,'Scenario not found')
    rate_limiter.check(f'experiment:{user.id}',6,300)
    r=ExperimentRun(facility_id=user.facility_id,scenario_version_id=s.id);db.add(r);db.flush()
    job=Job(facility_id=user.facility_id,type='EXPERIMENT',config_json=s.config_json,result_ref=str(r.id));db.add(job);db.flush()
    record_audit(db,facility_id=user.facility_id,actor_id=user.id,action='experiment.requested',object_type='ExperimentRun',object_id=r.id,correlation_id=key,new={'scenario_hash':s.config_hash})
    return {'id':str(r.id),'job_id':str(job.id),'status':'PENDING'}


@router.get('/runs',response_model=list[RunSummary])
def runs(user=RESEARCH,db:Session=DB):
    return [{'id':str(r.id),'scenario_version_id':str(r.scenario_version_id),'status':r.status,'created_at':r.created_at} for r in db.scalars(select(ExperimentRun).where(ExperimentRun.facility_id==user.facility_id).order_by(ExperimentRun.created_at.desc()).limit(100))]


def require_run(db,ident,facility):
    r=db.scalar(select(ExperimentRun).where(ExperimentRun.id==ident,ExperimentRun.facility_id==facility))
    if not r: raise HTTPException(404,'Experiment run not found')
    return r


@router.get('/runs/{run_id}',response_model=RunResponse)
def result(run_id:uuid.UUID,user=RESEARCH,db:Session=DB):
    r=require_run(db,run_id,user.facility_id)
    return {'id':str(r.id),'status':r.status,'scenario_version_id':str(r.scenario_version_id),'results':r.results_json}


@router.get('/runs/{run_id}/export')
def export(run_id:uuid.UUID,format:str='json',user=RESEARCH,db:Session=DB):
    r=require_run(db,run_id,user.facility_id)
    if r.status!='COMPLETED': raise HTTPException(409,'Experiment is not complete')
    data=r.results_json
    if format=='json': return Response(json.dumps(data),media_type='application/json',headers={'Content-Disposition':'attachment; filename=hutano-experiment.json'})
    if format=='csv':
        buffer=io.StringIO();w=csv.writer(buffer)
        for k in ['research_label','engine_version','config_hash','config','definitions','limitations']: w.writerow(['# '+k,json.dumps(data[k])])
        w.writerow(['demand_multiplier','policy','mean_wait_minutes','mean_replication_p90_minutes','completed_mean','unserved_mean','low_urgency_long_waits'])
        for s in data['sensitivities']:
            for policy,m in s['policies'].items(): w.writerow([s['demand_multiplier'],policy,*[m[k] for k in ['mean_wait_minutes','mean_replication_p90_minutes','completed_mean','unserved_mean','low_urgency_long_waits']]])
        return Response(buffer.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=hutano-experiment.csv'})
    if format=='svg':
        from app.services.reports import bar_svg
        base=next(s for s in data['sensitivities'] if s['demand_multiplier']==1)
        return Response(bar_svg('Synthetic assignment comparison: mean wait (minutes)',{p:m['mean_wait_minutes'] for p,m in base['policies'].items()}),media_type='image/svg+xml')
    raise HTTPException(422,'Choose json, csv or svg')
