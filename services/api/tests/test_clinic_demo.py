from datetime import datetime, timezone, timedelta
import uuid
from sqlalchemy import select, func
from app.demo_clinic import prepare_clinic, FACILITY_ID
from app.models import Visit, Patient, ServiceEpisode, ResourceAssignment, DemoSession, User, Observation, Job
from app.config import settings
from app.services.analytics import overview


def build(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings,"model_artifact_dir",tmp_path)
    result=prepare_clinic(db,now=datetime(2026,10,30,10,0,tzinfo=timezone.utc))
    db.commit()
    return result


def test_fictional_clinic_is_coherent_repeatable_and_preserves_original(db_session,monkeypatch,tmp_path):
    db=db_session
    original=list(db.scalars(select(User.id)))
    session=build(db,monkeypatch,tmp_path)
    assert session.manifest_json['historical_visits_added']==360
    assert len(session.manifest_json['cases'])==17
    case_patients=[db.get(Patient,uuid.UUID(c['patient_id'])) for c in session.manifest_json['cases']]
    assert len({p.pseudonym.split()[-1] for p in case_patients})==17
    assert db.scalar(select(func.count(Visit.id)).where(Visit.facility_id==FACILITY_ID))==377
    assert all(db.get(User,i) for i in original)
    assert prepare_clinic(db).id==session.id
    assert db.scalar(select(func.count(DemoSession.id)))==1
    assert set(db.scalars(select(Job.type).where(Job.facility_id==FACILITY_ID)))=={'MODEL_TRAIN','OPERATIONAL_TRAIN','SIMULATION'}
    assert all(p.synthetic_flag and not p.pseudonym.startswith('Synthetic') for p in db.scalars(select(Patient).where(Patient.facility_id==FACILITY_ID)))
    for visit in db.scalars(select(Visit).where(Visit.facility_id==FACILITY_ID)):
        assert visit.arrival_at<=session.anchor_at
        last=visit.arrival_at
        for ep in visit.episodes:
            assert ep.queued_at>=last
            if ep.started_at: assert ep.started_at>=ep.queued_at
            if ep.ended_at:
                assert ep.ended_at>=ep.started_at
                assert ep.ended_at<=session.anchor_at
                last=ep.ended_at
        if visit.status=='COMPLETED': assert visit.completed_at==visit.episodes[-1].ended_at
    assert db.scalar(select(func.count(ResourceAssignment.id)).where(ResourceAssignment.released_at.is_(None)))==2
    assert all(o.source=='fictional_demo' for o in db.scalars(select(Observation).where(Observation.facility_id==FACILITY_ID)))


def test_fresh_rehearsal_retires_only_scripted_cases(db_session,monkeypatch,tmp_path):
    db=db_session;first=build(db,monkeypatch,tmp_path)
    # Independently registered records in the same facility are outside the manifest.
    patient=db.scalars(select(Patient).where(Patient.facility_id==FACILITY_ID)).all()[-1]
    manual=Visit(facility_id=FACILITY_ID,patient_id=patient.id,public_token='MANUAL',token_secret_hash=b'x'*32,status='REGISTERING',arrival_at=first.anchor_at,token_day=first.anchor_at.date())
    db.add(manual);db.commit()
    second=prepare_clinic(db,fresh=True,now=first.anchor_at+timedelta(hours=1));db.commit()
    assert second.id!=first.id and second.manifest_json['historical_visits_added']==0
    assert db.get(Visit,manual.id).status=='REGISTERING'
    for item in first.manifest_json['cases']:
        v=db.get(Visit,uuid.UUID(item['visit_id']))
        assert v.status in {'CANCELLED','COMPLETED'}


def test_analytics_dates_filter_arrival_cohort_and_preserve_live_counts(db_session,monkeypatch,tmp_path):
    db=db_session;build(db,monkeypatch,tmp_path)
    from datetime import date
    all_rows=overview(db,FACILITY_ID)
    filtered=overview(db,FACILITY_ID,date(2026,10,30),date(2026,10,30))
    assert all_rows['visits_total']==377 and filtered['visits_total']==17
    assert filtered['completed_visits']==2
    assert filtered['reporting_filter']['timezone']=='Africa/Harare'
    assert filtered['daily_activity']==[{'day':'2026-10-30','arrivals':17,'completed':2}]


def test_snapshot_and_visit_search_are_role_and_facility_scoped(client,db_session,monkeypatch,tmp_path):
    build(db_session,monkeypatch,tmp_path)
    client.post('/api/v1/auth/login',json={'email':'research@showcase.hutano.test','password':'DemoResearch1!'})
    snapshot=client.get('/api/v1/clinic/snapshot').json()
    assert snapshot['facility']['name']=='Hutano Community Clinic'
    assert snapshot['demonstration']['cases']==[]
    assert snapshot['counts']['stored_visits']==377
    assert 'Rutendo Chari' not in str(snapshot)
    comparisons=client.get('/api/v1/simulations').json()
    assert len(comparisons)==1 and comparisons[0]['status']=='PENDING'
    assert client.get('/api/v1/analytics/overview?from_date=2026-10-30&to_date=2026-10-01').status_code==422
    assert client.get('/api/v1/analytics/overview?from_date=2024-01-01&to_date=2026-10-30').status_code==422
    client.cookies.clear()
    client.post('/api/v1/auth/login',json={'email':'clinician@showcase.hutano.test','password':'DemoClinician1!'})
    assert len(client.get('/api/v1/clinic/snapshot').json()['demonstration']['cases'])==17
    rows=client.get('/api/v1/visits',params={'q':'Rutendo Chari'}).json()
    assert rows and all(v['patient']['pseudonym']=='Rutendo Chari' for v in rows)
    assert len(client.get('/api/v1/visits',params={'limit':5}).json())==5
    assert client.get('/api/v1/simulations').status_code==403
    client.cookies.clear()
    client.post('/api/v1/auth/login',json={'email':'admin@test.local','password':'Testing123!'})
    assert client.get('/api/v1/clinic/snapshot').json()['demonstration'] is None
    assert client.get('/api/v1/simulations').json()==[]


def test_rehearsal_pause_resume_and_completion_notes_are_preserved(client,db_session,monkeypatch,tmp_path):
    from conftest import command_headers
    from app.models import AuditEvent
    monkeypatch.setattr(settings,'model_artifact_dir',tmp_path)
    session=prepare_clinic(db_session);db_session.commit()
    case=next(c for c in session.manifest_json['cases'] if c['initial_status']=='PAUSED')
    client.post('/api/v1/auth/login',json={'email':'clinician@showcase.hutano.test','password':'DemoClinician1!'})
    csrf=client.cookies['hutano_csrf']
    ep=client.get('/api/v1/visits/'+case['visit_id']).json()['episodes'][-1]
    resumed=client.post(f"/api/v1/episodes/{ep['id']}/start",json={'version':ep['version'],'reason':'Fictional patient returned to room'},headers=command_headers(csrf,str(uuid.uuid4())))
    assert resumed.status_code==200,resumed.text
    note='Fictional completion note retained in the longitudinal record.'
    finished=client.post(f"/api/v1/episodes/{ep['id']}/complete",json={'version':resumed.json()['version'],'operational_note':note},headers=command_headers(csrf,str(uuid.uuid4())))
    assert finished.status_code==200,finished.text
    workspace=client.get('/api/v1/patients/'+case['patient_id']+'/workspace').json()
    visit=next(v for v in workspace['visits'] if v['id']==case['visit_id'])
    assert visit['status']=='COMPLETED' and any(n['text']==note for n in visit['notes'])
    # The rehearsal seed also audits the episode's original start; the resume is the latest one.
    assert db_session.scalar(select(AuditEvent.reason).where(AuditEvent.object_id==ep['id'],AuditEvent.action=='episode.started').order_by(AuditEvent.occurred_at.desc()).limit(1))=='Fictional patient returned to room'


def test_cast_is_coherent_and_supports_the_advisory(db_session,monkeypatch,tmp_path):
    """Scripted people read like real attendances and carry enough vitals for the advisory."""
    from app.demo_cast import CAST
    from app.advisory import visit_inputs
    from app.ml.pipeline import MEASUREMENTS, MAX_MISSING_VITALS
    from app.models import EncounterNote, TriageAssessment
    db=db_session;session=build(db,monkeypatch,tmp_path)
    people=db.scalars(select(Patient).where(Patient.facility_id==FACILITY_ID)).all()
    assert all(p.sex in {'female','male'} and p.age_band and p.year_of_birth for p in people)
    women=sum(p.sex=='female' for p in people)/len(people)
    assert .45<women<.70
    by_name={c.name:c for c in CAST}
    visits={c['visit_id']:db.get(Visit,uuid.UUID(c['visit_id'])) for c in session.manifest_json['cases']}
    # Tokens rise with arrival time among today's scripted cases.
    ordered=sorted(visits.values(),key=lambda v:v.arrival_at)
    assert [v.public_token for v in ordered]==sorted(v.public_token for v in ordered)
    for case in session.manifest_json['cases']:
        visit=visits[case['visit_id']];cast=by_name[visit.patient.pseudonym]
        assert visit.visit_type==cast.visit_type and case['story']==cast.story
        earlier=db.scalar(select(func.count(Visit.id)).where(Visit.patient_id==visit.patient_id,Visit.id!=visit.id))
        assert (earlier>0)==cast.returning, cast.name
        if cast.category:
            values,_=visit_inputs(db,visit)
            missing=sum(all(values[f] is None for f in fields) for fields in MEASUREMENTS.values())
            assert missing<=MAX_MISSING_VITALS, cast.name
    texts=[n.text for n in db.scalars(select(EncounterNote).where(EncounterNote.facility_id==FACILITY_ID))]
    texts+=[t.reason for t in db.scalars(select(TriageAssessment).where(TriageAssessment.facility_id==FACILITY_ID))]
    assert texts and not any('Fictional rehearsal' in t or 'Scripted' in t for t in texts)
    # No diagnoses or prescriptions are seeded (ADR-017, ADR-037).
    assert not any(word in t.lower() for t in texts for word in ['diagnos','mg ','prescribed','tablets'])


def test_boot_refreshes_only_a_stale_rehearsal(db_session,monkeypatch,tmp_path):
    db=db_session;first=build(db,monkeypatch,tmp_path)
    assert prepare_clinic(db,if_stale=True,now=first.anchor_at+timedelta(hours=7)).id==first.id
    later=prepare_clinic(db,if_stale=True,now=first.anchor_at+timedelta(hours=9));db.commit()
    assert later.id!=first.id


def test_preparation_notes_hours_outside_the_clinic_day(db_session,monkeypatch,tmp_path):
    from app.demo_clinic import preparation_note
    from zoneinfo import ZoneInfo
    z=ZoneInfo('Africa/Harare')
    assert preparation_note(datetime(2026,11,23,10,0,tzinfo=z)) is None            # Monday morning
    assert 'outside typical clinic hours' in preparation_note(datetime(2026,11,23,22,0,tzinfo=z))
    assert 'outside typical clinic hours' in preparation_note(datetime(2026,11,22,10,0,tzinfo=z))  # Sunday
    session=build(db_session,monkeypatch,tmp_path)   # 10:00 UTC = 12:00 Friday in Harare
    assert session.manifest_json['preparation_note'] is None


def test_admin_prepares_a_fresh_rehearsal_from_the_browser(client,db_session,monkeypatch,tmp_path):
    from conftest import command_headers
    from app.models import AuditEvent
    first=build(db_session,monkeypatch,tmp_path)
    body={'reason':'Morning demonstration for the review panel'}
    client.post('/api/v1/auth/login',json={'email':'clinician@showcase.hutano.test','password':'DemoClinician1!'})
    assert client.post('/api/v1/clinic/demo/prepare',json=body,headers=command_headers(client.cookies['hutano_csrf'],str(uuid.uuid4()))).status_code==403
    client.cookies.clear()
    client.post('/api/v1/auth/login',json={'email':'admin@showcase.hutano.test','password':'DemoAdmin1!'})
    assert client.get('/api/v1/clinic/snapshot').json()['demonstration']['can_prepare'] is True
    done=client.post('/api/v1/clinic/demo/prepare',json=body,headers=command_headers(client.cookies['hutano_csrf'],str(uuid.uuid4())))
    assert done.status_code==200,done.text
    assert done.json()['session_id']!=str(first.id) and done.json()['cases']>0
    assert db_session.scalar(select(AuditEvent.reason).where(AuditEvent.action=='demo.rehearsal_requested'))==body['reason']
    for item in first.manifest_json['cases']:
        assert db_session.get(Visit,uuid.UUID(item['visit_id'])).status in {'CANCELLED','COMPLETED'}
    # The original research workspace can never be re-prepared from here.
    client.cookies.clear()
    client.post('/api/v1/auth/login',json={'email':'admin@test.local','password':'Testing123!'})
    assert client.post('/api/v1/clinic/demo/prepare',json=body,headers=command_headers(client.cookies['hutano_csrf'],str(uuid.uuid4()))).status_code==409


def test_advisory_is_enabled_only_when_preparation_asks(client,db_session,monkeypatch,tmp_path):
    from conftest import command_headers
    from app.models import ModelVersion, AuditEvent
    from app.worker import execute_job
    from app.demo_clinic import SCRIPTED_REVIEW_NOTE
    monkeypatch.setattr(settings,"model_artifact_dir",tmp_path)
    db=db_session
    plain=prepare_clinic(db);db.commit()
    job=db.scalar(select(Job).where(Job.facility_id==FACILITY_ID,Job.type=='MODEL_TRAIN'))
    execute_job(db,job);db.commit()
    model=db.scalar(select(ModelVersion).where(ModelVersion.facility_id==FACILITY_ID))
    assert model.status=='EXPERIMENTAL' and not model.active     # default: never reviewed for you
    session=prepare_clinic(db,fresh=True,enable_advisory=True);db.commit()
    job=db.scalar(select(Job).where(Job.id.in_([uuid.UUID(j) for j in session.manifest_json['jobs']]),Job.type=='MODEL_TRAIN'))
    execute_job(db,job);db.commit();db.refresh(model)
    assert model.status=='REVIEWED' and model.active and model.review_note==SCRIPTED_REVIEW_NOTE
    assert db.scalar(select(AuditEvent.actor_id).where(AuditEvent.action=='demo.advisory_enabled_by_preparation')) is None
    # Triaged scripted patients now get a suggestion or an abstention, not "unavailable".
    case=next(c for c in session.manifest_json['cases'] if c['initial_stage']=='consultation' and c['initial_status']=='WAITING')
    client.post('/api/v1/auth/login',json={'email':'clinician@showcase.hutano.test','password':'DemoClinician1!'})
    advice=client.post(f"/api/v1/visits/{case['visit_id']}/recommendation",json={},headers=command_headers(client.cookies['hutano_csrf'],str(uuid.uuid4())))
    assert advice.status_code==201,advice.text
    assert advice.json().get('available') is not False, advice.json()
