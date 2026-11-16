"""Opt-in integration tests use a fresh, isolated schema, never existing tables.

TEST_POSTGRES_URL=postgresql+psycopg://... pytest -q tests/test_postgres.py
"""
import importlib.util
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError
from app.main import app
from app.models import Facility, ServicePoint, User, UserRole, QueuePolicy, AuditEvent, QueueStateEvent
from app.security import hash_password
from conftest import login, command_headers
from test_workflow import create_registered_visit

pytestmark = pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'),reason='TEST_POSTGRES_URL required for real PostgreSQL integration')


@pytest.fixture()
def pg(monkeypatch):
    url=os.environ['TEST_POSTGRES_URL']
    assert url.startswith('postgresql')
    admin=create_engine(url)
    schema='hutano_test_'+uuid.uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    factory=sessionmaker(bind=engine,expire_on_commit=False,autoflush=False)
    for migration_path in sorted((Path(__file__).parents[1]/'migrations/versions').glob('*.py')):
        spec=importlib.util.spec_from_file_location(migration_path.stem,migration_path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
    import app.database as database
    import app.commands as commands
    import app.main as main
    monkeypatch.setattr(database,'SessionLocal',factory)
    monkeypatch.setattr(commands,'SessionLocal',factory)
    monkeypatch.setattr(main,'SessionLocal',factory)
    with factory() as db:
        f=Facility(name='Isolated Postgres test');db.add(f);db.flush()
        for kind in ['registration','triage','consultation','pharmacy']:
            db.add(ServicePoint(facility_id=f.id,name=kind.title(),type=kind,capacity=1))
        for email,role in [('reception@test.local','RECEPTIONIST'),('clinician@test.local','CLINICIAN')]:
            u=User(facility_id=f.id,email=email,display_name=role,password_hash=hash_password('Testing123!'))
            db.add(u);db.flush();db.add(UserRole(user_id=u.id,facility_id=f.id,role=role))
        db.add(QueuePolicy(facility_id=f.id,version='postgres-test-v1',config_json={'mode':'HYBRID'}));db.commit()
    try:
        with TestClient(app) as client:
            yield client, factory, engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            # Generated schema name only; contains no user-supplied SQL or existing data.
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


def test_real_postgres_concurrent_calls_and_append_only_audit(pg):
    client,factory,engine=pg
    csrf=login(client,'reception@test.local')
    visit=create_registered_visit(client,csrf)
    csrf=login(client,'clinician@test.local')
    response=client.post(f"/api/v1/visits/{visit['id']}/triage",json={'version':visit['version'],'configured_urgency':'P2'},headers=command_headers(csrf,str(uuid.uuid4())))
    assert response.status_code==201,response.text
    ep=client.get(f"/api/v1/visits/{visit['id']}").json()['episodes'][-1]
    entry=client.get(f"/api/v1/service-points/{ep['service_point_id']}/queue").json()['entries'][0]
    cookies=dict(client.cookies)
    def call(index):
        with TestClient(app) as independent:
            independent.cookies.update(cookies)
            return independent.post(f"/api/v1/queue/{entry['queue_entry_id']}/call",json={'version':entry['version']},headers=command_headers(csrf,f'parallel-call-{index}')).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(call,[1,2]))==[200,409]
    with factory() as db:
        called=db.scalars(select(QueueStateEvent).where(QueueStateEvent.to_status=='CALLED',QueueStateEvent.episode_id==uuid.UUID(ep['id']))).all()
        assert len(called)==1
        audit=db.scalar(select(AuditEvent).where(AuditEvent.action=='episode.called'))
        audit_id=audit.id
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text('UPDATE audit_events SET action=:action WHERE id=:id'),{'action':'tampered','id':audit_id})
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text('DELETE FROM audit_events WHERE id=:id'),{'id':audit_id})
    with factory() as db:
        assert db.get(AuditEvent,audit_id).action=='episode.called'


def test_postgres_completed_episode_database_constraints(pg):
    client,_,engine=pg
    csrf=login(client,'reception@test.local')
    visit=create_registered_visit(client,csrf)
    detail=client.get(f"/api/v1/visits/{visit['id']}").json()
    ep=detail['episodes'][0]
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE service_episodes SET started_at=queued_at - interval '1 hour' WHERE id=:id"),{'id':uuid.UUID(ep['id'])})


def test_postgres_migrations_upgrade_downgrade_upgrade(pg):
    from sqlalchemy import inspect
    _,_,engine=pg
    modules=[]
    for path in sorted((Path(__file__).parents[1]/'migrations/versions').glob('*.py')):
        spec=importlib.util.spec_from_file_location(path.stem,path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);modules.append(module)
    before=set(inspect(engine).get_table_names())
    assert 'visits' in before and 'audit_events' in before
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        for module in reversed(modules): module.downgrade()
    assert inspect(engine).get_table_names() == []
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        for module in modules: module.upgrade()
    assert set(inspect(engine).get_table_names()) == before
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM visits')) == 0


def test_postgres_atomic_room_reservation_and_workspace_history(pg):
    from datetime import timedelta
    from app.models import Room, StaffShift, ResourceAssignment, Observation, EncounterNote, utcnow
    client,factory,engine=pg
    csrf=login(client,'reception@test.local')
    visit=create_registered_visit(client,csrf)
    csrf=login(client,'clinician@test.local')
    response=client.post(f"/api/v1/visits/{visit['id']}/triage",json={'version':visit['version'],'configured_urgency':'P3','observations':{'pulse':80}},headers=command_headers(csrf,str(uuid.uuid4())))
    assert response.status_code==201,response.text
    ep=client.get(f"/api/v1/visits/{visit['id']}").json()['episodes'][-1]
    entry=client.get(f"/api/v1/service-points/{ep['service_point_id']}/queue").json()['entries'][0]
    with factory() as db:
        staff=db.scalar(select(User).where(User.email=='clinician@test.local'))
        room=Room(facility_id=staff.facility_id,service_point_id=uuid.UUID(ep['service_point_id']),name='Atomic PG room')
        db.add(room);db.flush();rid=str(room.id)
        db.add(StaffShift(facility_id=staff.facility_id,staff_id=staff.id,room_id=room.id,starts_at=utcnow()-timedelta(minutes=1),ends_at=utcnow()+timedelta(hours=2)));db.commit()
    proposals=[]
    for i in range(2):
        p=client.post('/api/v1/operations/proposals',json={'queue_entry_id':entry['queue_entry_id'],'version':entry['version']},headers=command_headers(csrf,str(uuid.uuid4())))
        assert p.status_code==201,p.text
        proposals.append(p.json()['id'])
    cookies=dict(client.cookies)
    def approve(proposal):
        with TestClient(app) as independent:
            independent.cookies.update(cookies)
            return independent.post(f'/api/v1/operations/proposals/{proposal}/approve',json={'room_id':rid,'reason':'Concurrent synthetic staff approval'},headers=command_headers(csrf,str(uuid.uuid4()))).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve,proposals))==[200,409]
    with factory() as db:
        assert len(list(db.scalars(select(ResourceAssignment))))==1
        a=db.scalar(select(ResourceAssignment))
        clone=ResourceAssignment(facility_id=a.facility_id,episode_id=a.episode_id,room_id=a.room_id,staff_id=a.staff_id,approved_by=a.approved_by)
        db.add(clone)
        with pytest.raises(DBAPIError): db.commit()
    response=client.post(f"/api/v1/episodes/{ep['id']}/notes",json={'text':'Preserved synthetic encounter note'},headers=command_headers(csrf,str(uuid.uuid4())))
    assert response.status_code==201,response.text
    with factory() as db:
        oid=db.scalar(select(Observation.id));nid=db.scalar(select(EncounterNote.id))
    for table,ident in [('observations',oid),('encounter_notes',nid)]:
        with pytest.raises(DBAPIError):
            with engine.begin() as conn:
                conn.execute(text(f'DELETE FROM {table} WHERE id=:id'),{'id':ident})


def test_postgres_new_metadata_matches_migration(pg):
    from alembic.autogenerate import compare_metadata
    from app.database import Base
    _,_,engine=pg
    with engine.connect() as conn:
        differences=compare_metadata(MigrationContext.configure(conn),Base.metadata)
    assert differences==[]


def test_postgres_research_evidence_immutability_and_concurrent_trials(pg):
    from app.models import (Dataset, ResearchProtocol, ResearchCase, CaseReview,
                            CaseAdjudication, ResearchTrial, ResearchStudyRun, DemoSession, utcnow)
    client, factory, engine = pg
    with factory() as db:
        clinician = db.scalar(select(User).where(User.email == 'clinician@test.local'))
        dataset = Dataset(facility_id=clinician.facility_id, name='Synthetic PG fixture', source_type='SYNTHETIC',
                          dataset_hash='b'*64, consent_basis_note='Database verification fixture only', schema_json={}, row_count=300)
        db.add(dataset); db.flush()
        protocol = ResearchProtocol(facility_id=clinician.facility_id, dataset_id=dataset.id, actor_id=clinician.id,
                                    name='Frozen PG protocol', question='Do database boundaries protect synthetic research?', design='MANUAL_ONLY',
                                    config_json={'case_count': 2, 'operations_config': {}}, config_hash='c'*64)
        db.add(protocol); db.flush()
        features = {'age_band': 'adult', 'visit_type': 'new', 'arrival_mode': 'walk_in', 'hour': 9, 'temperature': 37.0, 'pulse': 80., 'respiratory_rate': 16., 'oxygen_saturation': 97., 'systolic_pressure': 120., 'diastolic_pressure': 76.}
        reviewed = ResearchCase(facility_id=clinician.facility_id, protocol_id=protocol.id, ordinal=1,
                                features_json=features, synthetic_label='P2', source_row_hash='d'*64)
        unseen = ResearchCase(facility_id=clinician.facility_id, protocol_id=protocol.id, ordinal=2,
                              features_json={**features, 'hour': 10}, synthetic_label='P3', source_row_hash='e'*64)
        db.add_all([reviewed, unseen]); db.flush()
        review = CaseReview(facility_id=clinician.facility_id, case_id=reviewed.id, reviewer_id=clinician.id,
                            label='P2', reason='Synthetic PG reference fixture')
        adjudication = CaseAdjudication(facility_id=clinician.facility_id, case_id=reviewed.id, actor_id=clinician.id,
                                        label='P2', reason='Synthetic PG consensus fixture, API flow tested separately')
        run = ResearchStudyRun(facility_id=clinician.facility_id, protocol_id=protocol.id, status='COMPLETED', results_json={'fixture': True})
        db.add_all([review, adjudication, run]); db.flush()
        demo=DemoSession(facility_id=clinician.facility_id,version='pg-test',anchor_at=utcnow(),seed=2026,manifest_json={'fictional':True})
        db.add(demo);db.flush()
        immutable = [('research_protocols', protocol.id), ('research_cases', reviewed.id),
                     ('research_case_reviews', review.id), ('research_case_adjudications', adjudication.id), ('research_study_runs', run.id), ('demo_sessions', demo.id)]
        pid = str(protocol.id); db.commit()
    csrf = login(client, 'clinician@test.local'); cookies = dict(client.cookies)
    def start(i):
        with TestClient(app) as independent:
            independent.cookies.update(cookies)
            return independent.post(f'/api/v1/research/workbench/protocols/{pid}/trials/start',
                json={'consented': True, 'consent_ref': 'CONCURRENT_SYNTHETIC_TEST'}, headers=command_headers(csrf, f'research-start-{i}'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(start, range(2)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    tid = responses[0].json()['id']
    assert responses[1].json()['id'] == tid
    with factory() as db:
        trial = db.get(ResearchTrial, uuid.UUID(tid))
        clone = ResearchTrial(facility_id=trial.facility_id, protocol_id=trial.protocol_id, case_id=reviewed.id,
                              participant_id=trial.participant_id, arm='MANUAL', consent_ref='SECOND_ACTIVE_FIXTURE')
        db.add(clone)
        with pytest.raises(DBAPIError): db.commit()
    def finish(i):
        with TestClient(app) as independent:
            independent.cookies.update(cookies)
            return independent.post(f'/api/v1/research/workbench/trials/{tid}/complete',
                json={'label': 'P3', 'reason': 'Synthetic concurrency response', 'understands_authority': True, 'trust_rating': 3},
                headers=command_headers(csrf, f'research-finish-{i}')).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(finish, range(2))) == [200, 409]
    immutable.append(('research_trials', uuid.UUID(tid)))
    for table, ident in immutable:
        for query in [f'DELETE FROM {table} WHERE id=:id', f'UPDATE {table} SET id=id WHERE id=:id']:
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    connection.execute(text(query), {'id': ident})


def test_postgres_day_close_and_back_entry_respect_database_triggers(pg):
    """Day close cancels open episodes and appends an immutable closure; back-entry inserts
    completed episodes, which the completed-episode trigger allows (INSERT, not UPDATE)."""
    from datetime import timedelta
    from app.models import DayClosure, utcnow
    client,factory,engine=pg
    csrf=login(client,'reception@test.local')
    visit=create_registered_visit(client,csrf)
    patient=client.post('/api/v1/patients',json={'pseudonym':'Synthetic PG paper','synthetic_flag':True},headers=command_headers(csrf,str(uuid.uuid4()))).json()
    start=utcnow()-timedelta(hours=5)
    iso=lambda minutes:(start+timedelta(minutes=minutes)).isoformat()
    retro=client.post('/api/v1/operations/retrospective-visits',json={'patient_id':patient['id'],'arrival_at':iso(0),'paper_reference':'PG sheet #1',
        'reason':'Synthetic outage back-entry','outcome':'COMPLETED','stages':[{'service_type':'registration','queued_at':iso(0),'started_at':iso(1),'ended_at':iso(3)},
        {'service_type':'consultation','queued_at':iso(3),'started_at':iso(30),'ended_at':iso(40)}]},headers=command_headers(csrf,str(uuid.uuid4())))
    assert retro.status_code==201,retro.text
    csrf=login(client,'clinician@test.local')
    preview=client.get('/api/v1/operations/day-close').json()
    closed=client.post('/api/v1/operations/day-close',json={'local_date':preview['local_date'],'reason':'Synthetic end of day',
        'expected_open_count':preview['open_count']},headers=command_headers(csrf,str(uuid.uuid4())))
    assert closed.status_code==201,closed.text
    assert client.get(f"/api/v1/visits/{visit['id']}").json()['status']=='LEFT_WITHOUT_SERVICE'
    with factory() as db:
        closure_id=db.scalar(select(DayClosure.id))
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE day_closures SET reason='tampered' WHERE id=:id"),{'id':closure_id})
