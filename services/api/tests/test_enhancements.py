import uuid
from datetime import timedelta
import pandas as pd
import pytest
from sqlalchemy import select
from app.models import User, ServicePoint, ResourceAssignment, EncounterNote, Observation, utcnow, ExperimentScenarioVersion
from app.experiments import ExperimentConfig
from app.simulation.experiments import inputs, once, run_experiment
from app.operational_prediction import fit_duration, forecast
from conftest import login, command_headers
from test_workflow import create_registered_visit


def post(client,csrf,path,payload=None):
    return client.post('/api/v1'+path,json=payload,headers=command_headers(csrf,str(uuid.uuid4())))


def assessed(client):
    csrf=login(client,'reception@test.local');visit=create_registered_visit(client,csrf)
    csrf=login(client,'clinician@test.local')
    result=post(client,csrf,f"/visits/{visit['id']}/triage",{'version':visit['version'],'configured_urgency':'P3','observations':{'pulse':80}})
    assert result.status_code==201,result.text
    detail=client.get(f"/api/v1/visits/{visit['id']}").json()
    ep=detail['episodes'][-1]
    queue=client.get(f"/api/v1/service-points/{ep['service_point_id']}/queue").json()['entries'][0]
    return csrf,visit,ep,queue


def configured(client,db):
    csrf=login(client,'admin@test.local')
    point=db.scalar(select(ServicePoint).where(ServicePoint.type=='consultation'))
    staff=db.scalar(select(User).where(User.email=='clinician@test.local'))
    room=post(client,csrf,'/operations/rooms',{'name':'Consultation room 1','service_point_id':str(point.id)})
    assert room.status_code==201,room.text
    rid=room.json()['id'];now=utcnow()
    shift={'staff_id':str(staff.id),'room_id':rid,'starts_at':(now-timedelta(minutes=1)).isoformat(),'ends_at':(now+timedelta(hours=4)).isoformat()}
    response=post(client,csrf,'/operations/shifts',shift)
    assert response.status_code==201,response.text
    assert post(client,csrf,'/operations/shifts',shift).status_code==409
    return rid


def test_workspace_observations_notes_handovers_and_role_boundaries(client,db_session):
    csrf,visit,ep,_=assessed(client)
    patient=visit['patient']['id']
    response=post(client,csrf,f"/visits/{visit['id']}/observations",{'observations':[{'field_code':'temperature','value':36.8},{'field_code':'oxygen_saturation','value':None}]})
    assert response.json()=={'recorded':2,'priority_changed':False}
    assert post(client,csrf,f"/episodes/{ep['id']}/notes",{'text':'Synthetic service note, no diagnosis'}).status_code==201
    point=db_session.scalar(select(ServicePoint).where(ServicePoint.type=='pharmacy'))
    h=post(client,csrf,f"/episodes/{ep['id']}/handovers",{'target_point_id':str(point.id),'message':'Synthetic pharmacy handover'})
    assert h.status_code==201,h.text
    workspace=client.get(f'/api/v1/patients/{patient}/workspace').json()
    assert workspace['clinical_details_visible']
    encounter=workspace['visits'][0]
    assert encounter['observations'][0]['unit']=='beats/min'
    assert encounter['observations'][-1]['value'] is None
    assert encounter['notes'][0]['text']=='Synthetic service note, no diagnosis'
    assert encounter['assessments'][0]['urgency']=='P3'
    assert post(client,csrf,f"/handovers/{h.json()['id']}/acknowledge",{'version':1}).status_code==403
    csrf=login(client,'pharmacy@test.local')
    assert client.get('/api/v1/handovers').json()[0]['message']=='Synthetic pharmacy handover'
    assert post(client,csrf,f"/handovers/{h.json()['id']}/acknowledge",{'version':1}).status_code==200
    assert post(client,csrf,f"/handovers/{h.json()['id']}/acknowledge",{'version':1}).status_code==409
    assert client.get(f'/api/v1/patients/{patient}/workspace').status_code==403
    login(client,'reception@test.local')
    response=client.get(f'/api/v1/patients/{patient}/workspace').json()
    assert not response['clinical_details_visible'] and not response['visits'][0]['notes']
    login(client,'other@test.local')
    assert client.get('/api/v1/operations/board').json()['rooms']==[]
    login(client,'research@test.local')
    assert client.get(f'/api/v1/patients/{patient}/workspace').status_code==403


def test_structured_observations_validate_duplicates_and_values(client):
    csrf,visit,_,_=assessed(client)
    for values in [[{'field_code':'diagnosis','value':2}],[{'field_code':'pulse','value':2}]*2]:
        assert post(client,csrf,f"/visits/{visit['id']}/observations",{'observations':values}).status_code==422


def test_approved_assignment_stale_snapshots_and_release(client,db_session):
    rid=configured(client,db_session)
    csrf,visit,ep,queue=assessed(client)
    assert post(client,csrf,f"/queue/{queue['queue_entry_id']}/call",{'version':queue['version']}).status_code==409
    proposal=post(client,csrf,'/operations/proposals',{'queue_entry_id':queue['queue_entry_id'],'version':queue['version']})
    assert proposal.status_code==201,proposal.text
    assert proposal.json()['recommended_room_id']==rid
    admin=login(client,'admin@test.local');now=utcnow()
    assert post(client,admin,'/operations/blocks',{'room_id':rid,'starts_at':(now-timedelta(seconds=1)).isoformat(),'ends_at':(now+timedelta(minutes=10)).isoformat(),'reason':'Synthetic outage'}).status_code==201
    csrf=login(client,'clinician@test.local')
    assert post(client,csrf,f"/operations/proposals/{proposal.json()['id']}/approve",{'room_id':rid,'reason':'Approved by staff'}).status_code==409
    assert db_session.scalar(select(ResourceAssignment.id)) is None


def test_assignment_cannot_double_book_and_no_show_releases(client,db_session):
    rid=configured(client,db_session)
    csrf,visit,ep,queue=assessed(client)
    proposal=post(client,csrf,'/operations/proposals',{'queue_entry_id':queue['queue_entry_id'],'version':queue['version']}).json()
    result=post(client,csrf,f"/operations/proposals/{proposal['id']}/approve",{'room_id':rid,'reason':'Approved compatible room'})
    assert result.status_code==200,result.text
    assert result.json()['priority_changed'] is False
    assert not client.get('/api/v1/operations/board').json()['rooms'][0]['available']
    assert post(client,csrf,f"/operations/proposals/{proposal['id']}/approve",{'room_id':rid,'reason':'Duplicate attempt'}).status_code==409
    ep=client.get(f"/api/v1/visits/{visit['id']}").json()['episodes'][-1]
    assert post(client,csrf,f"/episodes/{ep['id']}/state",{'action':'NO_SHOW','version':ep['version'],'reason':'Synthetic absence'}).status_code==200
    assert client.get('/api/v1/operations/board').json()['rooms'][0]['available']
    assignment=db_session.scalar(select(ResourceAssignment))
    assert assignment.released_at is not None


def test_scenario_versions_job_scope_and_exports_pending(client,db_session):
    csrf=login(client,'research@test.local')
    config=ExperimentConfig(replications=1,demand_multipliers=[1]).model_dump(mode='json')
    body={'name':'Busy clinic','rationale':'Synthetic reproducible comparison','config':config}
    first=post(client,csrf,'/experiments/scenarios',body)
    assert first.status_code==201,first.text
    body.update(series_id=first.json()['series_id'],previous_revision=1)
    second=post(client,csrf,'/experiments/scenarios',body)
    assert second.json()['revision']==2
    assert post(client,csrf,'/experiments/scenarios',body).status_code==409
    assert len(list(db_session.scalars(select(ExperimentScenarioVersion))))==2
    queued=post(client,csrf,f"/experiments/scenarios/{second.json()['id']}/run")
    assert queued.status_code==202,queued.text
    ident=queued.json()['id']
    assert client.get(f'/api/v1/experiments/runs/{ident}/export').status_code==409
    login(client,'other@test.local')
    assert client.get(f'/api/v1/experiments/runs/{ident}').status_code==404
    assert client.get('/api/v1/experiments/scenarios').json()==[]


def test_finite_day_experiment_reproducible_distinct_and_incomplete():
    config=ExperimentConfig(replications=2,demand_multipliers=[1]).model_dump(mode='json')
    a=run_experiment(config);b=run_experiment(config)
    assert a==b
    assert len(a['input_hashes'])==2
    base=a['sensitivities'][0]['policies']
    assert base['FIXED_ROOM']['mean_wait_minutes']!=base['CAPACITY_AWARE']['mean_wait_minutes']
    assert a['replay']['NEXT_AVAILABLE']['assignments']!=a['replay']['CAPACITY_AWARE']['assignments']
    assert a['sensitivities'][0]['paired_95_ci'] is not None
    traces=a['replay']['CAPACITY_AWARE']['traces']
    assert any(t['stage']=='consultation_return' for steps in traces.values() for t in steps)
    config['blocks']=[{'room':i,'start':0,'duration':480,'kind':'ROOM_OUTAGE'} for i in range(3)]
    outcome=once(inputs(config,2026),config,'CAPACITY_AWARE')
    assert outcome['completed']==0 and outcome['unserved']>0
    assert outcome['waiting_minutes']['mean'] is None
    assert all(r['utilisation'] is None for r in outcome['rooms'])
    assert any(t['status']=='WAITING' for steps in outcome['traces'].values() for t in steps)


def test_resource_choice_is_not_patient_duration_priority():
    config=ExperimentConfig(replications=1,demand_multipliers=[1]).model_dump(mode='json')
    config['blocks']=[];config['room_shifts']=[[0,480]]*3
    cohort=inputs(config,2026)
    # One clearly available patient; algorithms differ by resource choice, not rank.
    cohort=cohort[:1];cohort[0].update(arrival=0,lab=False,no_show=False)
    first=once(cohort,config,'NEXT_AVAILABLE')['assignments'][0]
    chosen=once(cohort,config,'CAPACITY_AWARE')['assignments'][0]
    assert first['patient_no']==chosen['patient_no']
    assert first['room']==1 and chosen['room']==2


def test_temporal_operational_model_baseline_and_reproducibility(tmp_path):
    rows=[];start=utcnow()-timedelta(days=100)
    for i in range(90):
        for j,stage in enumerate(['triage','consultation']):
            at=start+timedelta(days=i,minutes=j*30);duration=4+j*8+(i%4)
            if i%2: at=at.replace(microsecond=0) # Mixed ISO precision must not break temporal purging.
            rows.append({'group':str(i),'stage':stage,'visit_type':'walk_in','hour':at.hour,'weekday':at.weekday(),'queued_at':at.isoformat(),'ended_at':(at+timedelta(minutes=duration)).isoformat(),'duration':duration})
    result=fit_duration(pd.DataFrame(rows),tmp_path)
    assert result['version']==fit_duration(pd.DataFrame(rows),tmp_path)['version']
    metrics=result['metrics']
    assert metrics['test_rows']==36 and metrics['calibration_rows']==36
    assert 0<=metrics['test_interval_coverage']<=1
    assert metrics['median_baseline_mae_minutes']>=0
    assert 'urgency' not in metrics['features'] and 'group' not in metrics['features']
    with pytest.raises(ValueError,match='100 completed'):
        fit_duration(pd.DataFrame(rows[:20]),tmp_path)


def test_operational_prediction_insufficient_history_and_role_checks(client,db_session):
    csrf=login(client,'research@test.local')
    report=client.get('/api/v1/operations/prediction').json()
    assert report['model'] is None and report['forecast']['available'] is False
    assert post(client,csrf,'/operations/prediction/train').status_code==202
    csrf=login(client,'reception@test.local')
    assert post(client,csrf,'/operations/prediction/train').status_code==403
    assert client.get('/api/v1/operations/prediction').status_code==403


def test_started_work_survives_outage_and_releases_on_completion(client,db_session):
    rid=configured(client,db_session);csrf,visit,ep,queue=assessed(client)
    proposal=post(client,csrf,'/operations/proposals',{'queue_entry_id':queue['queue_entry_id'],'version':queue['version']}).json()
    assert post(client,csrf,f"/operations/proposals/{proposal['id']}/approve",{'room_id':rid,'reason':'Synthetic approval'}).status_code==200
    ep=client.get(f"/api/v1/visits/{visit['id']}").json()['episodes'][-1]
    started=post(client,csrf,f"/episodes/{ep['id']}/start",{'version':ep['version']})
    assert started.status_code==200,started.text
    admin=login(client,'admin@test.local');now=utcnow()
    block=post(client,admin,'/operations/blocks',{'room_id':rid,'starts_at':now.isoformat(),'ends_at':(now+timedelta(minutes=10)).isoformat(),'reason':'Synthetic outage during service'})
    assert block.status_code==201
    assert not block.json()['in_progress_service_interrupted']
    assert post(client,admin,f"/operations/schedule/blocks/{block.json()['id']}/cancel",{'version':1,'reason':'Cannot erase history'}).status_code==409
    csrf=login(client,'clinician@test.local')
    completed=post(client,csrf,f"/episodes/{ep['id']}/complete",{'version':started.json()['version'],'next_service_type':None})
    assert completed.status_code==200,completed.text
    assert db_session.scalar(select(ResourceAssignment)).released_at is not None
    assert not client.get('/api/v1/operations/board').json()['rooms'][0]['available']


def test_reserved_work_cannot_start_through_new_outage(client,db_session):
    rid=configured(client,db_session);csrf,visit,ep,queue=assessed(client)
    proposal=post(client,csrf,'/operations/proposals',{'queue_entry_id':queue['queue_entry_id'],'version':queue['version']}).json()
    post(client,csrf,f"/operations/proposals/{proposal['id']}/approve",{'room_id':rid,'reason':'Synthetic approval'})
    admin=login(client,'admin@test.local');now=utcnow()
    post(client,admin,'/operations/blocks',{'room_id':rid,'starts_at':now.isoformat(),'ends_at':(now+timedelta(minutes=10)).isoformat(),'reason':'Synthetic outage before service'})
    csrf=login(client,'clinician@test.local');ep=client.get(f"/api/v1/visits/{visit['id']}").json()['episodes'][-1]
    assert post(client,csrf,f"/episodes/{ep['id']}/start",{'version':ep['version']}).status_code==409
    assert db_session.scalar(select(ResourceAssignment)).started_at is None
    assert client.get(f"/api/v1/visits/{visit['id']}").json()['episodes'][-1]['status']=='CALLED'


def test_forecast_observed_days_and_next_hour_interpolation(db_session):
    from app.models import Facility,Patient,Visit
    now=utcnow().replace(hour=8,minute=30,second=0,microsecond=0)
    facility=db_session.scalar(select(Facility).where(Facility.name=='Test Demo Clinic'))
    for day in range(1,10):
        patient=Patient(facility_id=facility.id,pseudonym=f'Synthetic forecast {day}',synthetic_flag=True)
        db_session.add(patient);db_session.flush()
        at=now-timedelta(days=day)
        db_session.add(Visit(facility_id=facility.id,patient_id=patient.id,public_token=f'Forecast-{day}',token_day=at.date(),token_secret_hash=bytes([day])*32,arrival_at=at,status='COMPLETED'))
    db_session.commit()
    result=forecast(db_session,facility.id,now)
    assert result['available'] and result['observation_days']==9
    # One observed arrival in current hour, zero in following hour, half-hour remaining.
    assert result['expected_arrivals_next_hour']==.5
    assert not result['stale_history']
    assert result['walk_forward_mae_arrivals_per_hour']==0


def test_experiment_worker_persists_exports_and_failure(client,db_session):
    from app.models import Job, ExperimentRun
    from app.worker import work_once
    from sqlalchemy.orm import sessionmaker
    csrf=login(client,'research@test.local')
    config=ExperimentConfig(replications=1,demand_multipliers=[1]).model_dump(mode='json')
    scenario=post(client,csrf,'/experiments/scenarios',{'name':'Worker scenario','rationale':'Synthetic worker test','config':config}).json()
    queued=post(client,csrf,f"/experiments/scenarios/{scenario['id']}/run").json()
    factory=sessionmaker(bind=db_session.get_bind(),expire_on_commit=False,autoflush=False)
    assert work_once(factory)
    db_session.expire_all()
    assert client.get(f"/api/v1/experiments/runs/{queued['id']}").json()['status']=='COMPLETED'
    for fmt in ['json','csv','svg']:
        response=client.get(f"/api/v1/experiments/runs/{queued['id']}/export?format={fmt}")
        assert response.status_code==200,response.text
    queued=post(client,csrf,f"/experiments/scenarios/{scenario['id']}/run").json()
    job=db_session.get(Job,uuid.UUID(queued['job_id']));job.config_json={};db_session.commit()
    assert work_once(factory);db_session.expire_all()
    assert db_session.get(ExperimentRun,uuid.UUID(queued['id'])).status=='FAILED'
