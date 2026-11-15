"""Operational duration prediction only; never a patient-priority feature."""
import hashlib
import json
import uuid
from datetime import timedelta
from datetime import datetime
from typing import Any
from pathlib import Path
from zoneinfo import ZoneInfo
import joblib
import numpy as np
import pandas as pd
import sklearn
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from app.commands import CommandRoute
from app.schemas import APIModel
from app.workspace_contracts import DurationResponse
from app.config import settings
from app.database import get_db
from app.models import OperationalModel, ServiceEpisode, Visit, Facility, Job, utcnow
from app.security import require_roles, rate_limiter, CurrentUser
from app.access import service_action
from app.services.workflow import require_episode
from app.services.analytics import effective_time
from app.services.audit import record_audit

router=APIRouter(prefix='/api/v1/operations',route_class=CommandRoute)
DB=Depends(get_db,scope='function')
FEATURES=['stage','visit_type','hour','weekday']
VERSION='operational-duration-v1'
WARNING='Synthetic operational prediction; not a clinical recommendation or promised service time'


class ForecastResponse(APIModel):
    available:bool
    warning:str
    reason:str|None=None
    basis:str|None=None
    observation_days:int|None=None
    hour:int|None=None
    expected_arrivals_next_hour:float|None=None
    historical_hour_range:list[float]|None=None
    range_kind:str|None=None
    walk_forward_mae_arrivals_per_hour:float|None=None
    constant_baseline_mae:float|None=None
    stale_history:bool|None=None
    last_observed_day:str|None=None


class OperationalModelResponse(APIModel):
    version:str
    created_at:datetime
    metrics:dict[str,Any]


class PredictionResponse(APIModel):
    model:OperationalModelResponse|None
    forecast:ForecastResponse


def duration_rows(db,facility_id):
    rows=[]
    zone=ZoneInfo(db.get(Facility,facility_id).timezone)
    for e in db.scalars(select(ServiceEpisode).where(ServiceEpisode.facility_id==facility_id,ServiceEpisode.status=='COMPLETED')):
        if not e.started_at or not e.ended_at or not e.queued_at or not e.visit.patient.synthetic_flag: continue
        queued=effective_time(e,'queued_at');started=effective_time(e,'started_at');ended=effective_time(e,'ended_at')
        minutes=((ended-started).total_seconds()-e.paused_seconds)/60
        if not .1<=minutes<=1440: continue
        local=queued.astimezone(zone)
        rows.append({'stage':e.service_point.type,'visit_type':e.visit.visit_type,'hour':local.hour,'weekday':local.weekday(),
            'duration':minutes,'queued_at':queued.isoformat(),'ended_at':ended.isoformat(),'group':str(e.visit_id)})
    return pd.DataFrame(rows).sort_values(['queued_at','stage','ended_at']).reset_index(drop=True) if rows else pd.DataFrame()


def fit_duration(frame,artifact_dir):
    if len(frame)<100 or frame['group'].nunique()<30: raise ValueError('At least 100 completed stages from 30 synthetic visits are required')
    # Whole visits stay in one partition, and training outcomes must be known
    # before the next partition starts. This avoids repeat-stage/future leakage.
    groups=frame.groupby('group',sort=False).queued_at.min().sort_values()
    n=len(groups);a=max(1,int(n*.6));b=max(a+1,int(n*.8))
    train=frame[frame.group.isin(groups.index[:a])].copy()
    calibration=frame[frame.group.isin(groups.index[a:b])].copy()
    test=frame[frame.group.isin(groups.index[b:])].copy()
    train=train[pd.to_datetime(train.ended_at,utc=True,format="ISO8601")<pd.to_datetime(calibration.queued_at,utc=True,format="ISO8601").min()]
    calibration=calibration[pd.to_datetime(calibration.ended_at,utc=True,format="ISO8601")<pd.to_datetime(test.queued_at,utc=True,format="ISO8601").min()]
    if min(len(train),len(calibration),len(test))<15: raise ValueError('Insufficient non-overlapping temporal partitions')
    categorical=['stage','visit_type']
    def estimator(q):
        return Pipeline([('encode',ColumnTransformer([('categories',OneHotEncoder(handle_unknown='ignore',sparse_output=False),categorical),('numeric','passthrough',['hour','weekday'])])),
            ('regressor',GradientBoostingRegressor(loss='quantile',alpha=q,n_estimators=60,max_depth=2,random_state=2026))])
    models={str(q):estimator(q).fit(train[FEATURES],train.duration) for q in [.1,.5,.9]}
    medians=train.groupby('stage').duration.median().to_dict()
    baseline=lambda f: np.array([medians.get(s,float(train.duration.median())) for s in f.stage])
    candidate_mae=float(np.mean(abs(models['0.5'].predict(calibration[FEATURES])-calibration.duration)))
    baseline_cal=float(np.mean(abs(baseline(calibration)-calibration.duration)))
    selected='quantile_gradient_boosting' if candidate_mae<baseline_cal else 'stage_median'
    def raw(f):
        if selected=='stage_median':
            values=baseline(f);return values,values,values
        vals=np.sort(np.stack([models[str(q)].predict(f[FEATURES]) for q in [.1,.5,.9]]),axis=0)
        return vals[0],vals[1],vals[2]
    lo,_,hi=raw(calibration)
    scores=np.maximum.reduce([lo-calibration.duration.to_numpy(),calibration.duration.to_numpy()-hi,np.zeros(len(calibration))])
    margin=float(np.quantile(scores,min(1,np.ceil((len(scores)+1)*.8)/len(scores)),method='higher'))
    lo,mid,hi=raw(test);lo=np.maximum(.1,lo-margin);hi=np.maximum(lo,hi+margin)
    # Exclude identifiers from provenance hashes and exported metadata.
    provenance=frame.drop(columns=['group']).to_csv(index=False).encode()
    digest=hashlib.sha256(provenance).hexdigest()
    implementation=hashlib.sha256(f'{VERSION}:{sklearn.__version__}:{np.__version__}'.encode()).hexdigest()[:8]
    version=f'ops-{digest[:12]}-{implementation}'
    metrics={'source':'SYNTHETIC_OPERATIONAL','warning':WARNING,'version':version,'dataset_hash':digest,'selected_estimator':selected,
        'selection_basis':'Calibration-partition MAE; untouched temporal test partition used only for reporting',
        'train_rows':len(train),'calibration_rows':len(calibration),'test_rows':len(test),'visit_groups':n,
        'split':'Chronological whole-visit 60/20/20 with outcome-availability purge; no visit crosses partitions',
        'test_start':str(test.queued_at.min()),'features':FEATURES,'mae_minutes':float(np.mean(abs(mid-test.duration))),
        'median_baseline_mae_minutes':float(np.mean(abs(baseline(test)-test.duration))),
        'candidate_calibration_mae_minutes':candidate_mae,'baseline_calibration_mae_minutes':baseline_cal,
        'nominal_interval_coverage':.8,'test_interval_coverage':float(np.mean((test.duration>=lo)&(test.duration<=hi))),
        'mean_interval_width_minutes':float(np.mean(hi-lo)),'calibration_margin_minutes':margin,
        'limitations':['Intervals are marginal, not individual guarantees','Distribution shift can invalidate coverage','No clinical urgency or treatment inference'],
        'stage_samples':{str(k):int(v) for k,v in train.stage.value_counts().items()}}
    artifact_dir=Path(artifact_dir);artifact_dir.mkdir(parents=True,exist_ok=True);path=artifact_dir/f'{version}.joblib'
    joblib.dump({'models':models,'medians':medians,'margin':margin,'selected':selected,'metrics':metrics,
        'visit_types':list(train.visit_type.unique()),'stages':list(train.stage.unique())},path);path.chmod(0o600)
    return {'version':version,'dataset_hash':digest,'artifact_path':str(path),'metrics':metrics}


def estimate_duration(db,episode):
    model=db.scalar(select(OperationalModel).where(OperationalModel.facility_id==episode.facility_id).order_by(OperationalModel.created_at.desc()).limit(1))
    unavailable={'available':False,'warning':WARNING,'reason':'No evaluated operational model; historical fallback only'}
    if not model: return unavailable
    try: artifact=joblib.load(model.artifact_path)
    except (OSError,ValueError): return {**unavailable,'reason':'Private model artifact unavailable'}
    stage=episode.service_point.type;visit_type=episode.visit.visit_type
    if artifact['metrics']['stage_samples'].get(stage,0)<10 or visit_type not in artifact['visit_types']:
        return {**unavailable,'reason':'Insufficient or unseen service/visit data'}
    local=(episode.queued_at or utcnow()).astimezone(ZoneInfo(db.get(Facility,episode.facility_id).timezone))
    frame=pd.DataFrame([{'stage':stage,'visit_type':visit_type,'hour':local.hour,'weekday':local.weekday()}])
    if artifact['selected']=='stage_median': values=np.repeat(artifact['medians'][stage],3)
    else: values=np.sort([artifact['models'][str(q)].predict(frame)[0] for q in [.1,.5,.9]])
    return {'available':True,'minimum_minutes':round(max(.1,float(values[0])-artifact['margin']),2),'median_minutes':round(max(.1,float(values[1])),2),
        'maximum_minutes':round(max(.1,float(values[2])+artifact['margin']),2),'model_version':model.version,'dataset_hash':model.dataset_hash,
        'nominal_coverage':.8,'measured_test_coverage':artifact['metrics']['test_interval_coverage'],'warning':WARNING,'priority_effect':'NONE'}


def forecast(db,facility_id,now=None):
    now=now or utcnow();zone=ZoneInfo(db.get(Facility,facility_id).timezone);local=now.astimezone(zone)
    visits=list(db.scalars(select(Visit).where(Visit.facility_id==facility_id,Visit.arrival_at<now)))
    counts={}
    for v in visits:
        at=v.arrival_at.astimezone(zone)
        if at.date()>=local.date(): continue
        counts.setdefault(at.date(),np.zeros(24))[at.hour]+=1
    days=sorted(counts)
    if len(days)<7: return {'available':False,'reason':'At least seven recorded observation days are required','warning':WARNING}
    # No zero-visit day is invented as an observed opening day.
    data=np.array([counts[d] for d in days]);errors=[];base_errors=[]
    for i in range(4,len(data)):
        errors.extend(abs(data[max(0,i-7):i].mean(axis=0)-data[i]));base_errors.extend(abs(np.full(24,data[:i].mean())-data[i]))
    fraction=(local.minute*60+local.second)/3600
    hourly=(1-fraction)*data[-7:,local.hour]+fraction*data[-7:,(local.hour+1)%24]
    return {'available':True,'basis':'Next 60 minutes interpolated from rolling observed-day hourly means; calendar periods without records are unknown, not zero',
        'observation_days':len(days),'hour':local.hour,'expected_arrivals_next_hour':round(float(hourly.mean()),2),
        'historical_hour_range':[float(np.quantile(hourly,.1)),float(np.quantile(hourly,.9))],
        'range_kind':'Descriptive historical spread, not a calibrated forecast interval',
        'walk_forward_mae_arrivals_per_hour':round(float(np.mean(errors)),3),'constant_baseline_mae':round(float(np.mean(base_errors)),3),
        'stale_history':(local.date()-days[-1]).days>7,'last_observed_day':days[-1].isoformat(),'warning':WARNING}


@router.post('/prediction/train',status_code=202)
def train(user=Depends(require_roles('ADMIN','MANAGER','RESEARCHER')),db:Session=DB,key:str=Header(alias='Idempotency-Key')):
    rate_limiter.check(f'operational-training:{user.id}',3,300)
    job=Job(facility_id=user.facility_id,type='OPERATIONAL_TRAIN',config_json={});db.add(job);db.flush()
    record_audit(db,facility_id=user.facility_id,actor_id=user.id,action='operational.training_requested',object_type='Job',object_id=job.id,correlation_id=key,new={'synthetic':True})
    return {'job_id':str(job.id),'status':job.status}


@router.get('/prediction',response_model=PredictionResponse)
def report(user=Depends(require_roles('ADMIN','MANAGER','RESEARCHER','CLINICIAN')),db:Session=DB):
    model=db.scalar(select(OperationalModel).where(OperationalModel.facility_id==user.facility_id).order_by(OperationalModel.created_at.desc()).limit(1))
    return {'model':{'version':model.version,'created_at':model.created_at,'metrics':model.metrics_json} if model else None,'forecast':forecast(db,user.facility_id)}


@router.get('/episodes/{episode_id}/estimate',response_model=DurationResponse)
def estimate(episode_id:uuid.UUID,user:CurrentUser,db:Session=DB):
    ep=require_episode(db,episode_id,user.facility_id);service_action(user,ep)
    return estimate_duration(db,ep)
