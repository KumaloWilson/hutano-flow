import asyncio
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import EventOutbox, Facility, Job, User, utcnow
from app.security import create_session_token
from app.services.events import visible_event, invalidation
from app.worker import work_once
from conftest import login, command_headers


def test_login_and_token_rate_limits_are_enforced(client):
    for _ in range(10):
        assert client.post('/api/v1/auth/login',json={'email':'unknown@test.local','password':'Incorrect123!'}).status_code == 401
    assert client.post('/api/v1/auth/login',json={'email':'unknown@test.local','password':'Incorrect123!'}).status_code == 429
    for _ in range(20):
        assert client.post('/api/v1/patient-status/lookup',json={'token':'invalid-private-token-1234567890'}).status_code == 404
    assert client.post('/api/v1/patient-status/lookup',json={'token':'invalid-private-token-1234567890'}).status_code == 429


def test_oversize_body_origin_and_sensitive_validation(client):
    assert client.post('/api/v1/auth/login',content='x'*70000).status_code == 413
    response=client.post('/api/v1/auth/login',json={'email':'invalid sensitive text','password':'secret text'})
    assert response.status_code == 422 and 'sensitive text' not in response.text and 'secret text' not in response.text
    response=client.post('/api/v1/auth/login',headers={'Origin':'https://untrusted.invalid'},json={'email':'a@test.local','password':'Incorrect123!'})
    assert response.status_code == 403


@pytest.mark.parametrize('changes', [
    {'seed':-1}, {'outage':{'start_minute':0,'duration_minutes':10,'available_servers':'many'}},
    {'outage':{'start_minute':None,'duration_minutes':10}}, {'urgency_mix':[1,1,1,1,1]},
    {'stage_capacities':{'unknown':1}}, {'patient_count':5000,'replications':100},
])
def test_invalid_simulation_is_rejected_before_job_creation(client,db_session,changes):
    csrf=login(client,'research@test.local')
    response=client.post('/api/v1/simulations',json=changes,headers=command_headers(csrf,str(uuid.uuid4())))
    assert response.status_code == 422, response.text
    assert db_session.scalar(select(Job)) is None


def test_non_synthetic_upload_metadata_is_rejected(client):
    csrf=login(client,'research@test.local')
    response=client.post('/api/v1/research/datasets/import',files={'file':('data.csv',b'x\n1\n','text/csv')},
        data={'name':'Incorrect label','source_type':'AUTHORISED_RETROSPECTIVE','consent_basis_note':'No approval established'},
        headers=command_headers(csrf,str(uuid.uuid4())))
    assert response.status_code == 422, response.text


def test_worker_recovers_stale_lease_and_records_failure(db_session):
    facility=db_session.scalar(select(Facility).where(Facility.name=='Test Demo Clinic'))
    job=Job(facility_id=facility.id,type='UNKNOWN',status='RUNNING',attempt_count=1,
            updated_at=utcnow()-timedelta(minutes=20),config_json={})
    db_session.add(job);db_session.commit()
    factory=sessionmaker(bind=db_session.get_bind(),expire_on_commit=False,autoflush=False)
    assert work_once(factory)
    db_session.expire_all()
    assert job.status == 'FAILED' and job.attempt_count == 2
    assert job.error_summary == 'Unknown research job type'
    assert not work_once(factory)


def test_event_minimisation_and_research_role_boundary(db_session):
    clinician=db_session.scalar(select(User).where(User.email=='clinician@test.local'))
    researcher=db_session.scalar(select(User).where(User.email=='research@test.local'))
    other=db_session.scalar(select(User).where(User.email=='other@test.local'))
    event=EventOutbox(id=uuid.uuid4(),facility_id=clinician.facility_id,topic='visit.created',aggregate_id=str(uuid.uuid4()),
        aggregate_version=1,created_at=utcnow(),payload_json={'pseudonym':'never broadcast','observations':{'secret':1}})
    assert visible_event(db_session,clinician,event)
    assert not visible_event(db_session,researcher,event)
    assert not visible_event(db_session,other,event)
    assert invalidation(event)['data'] == {}
    assert 'secret' not in json.dumps(invalidation(event))
    event.topic='simulation.completed'
    assert visible_event(db_session,researcher,event)


@pytest.mark.asyncio
async def test_sse_cursor_crosses_same_timestamp_page_and_revocation_stops_stream(db_session,monkeypatch):
    import app.main as main
    user=db_session.scalar(select(User).where(User.email=='clinician@test.local'))
    at=utcnow()-timedelta(seconds=1)
    records=[EventOutbox(id=uuid.UUID(int=i+1),facility_id=user.facility_id,topic='visit.created',
        aggregate_id=str(uuid.uuid4()),created_at=at,payload_json={'private':'must not appear'}) for i in range(106)]
    db_session.add_all(records);db_session.commit()
    factory=sessionmaker(bind=db_session.get_bind(),expire_on_commit=False,autoflush=False)
    import threading
    event_loop_thread=threading.get_ident()
    def background_session():
        assert threading.get_ident()!=event_loop_thread, 'SSE database checkout must not block the ASGI event loop'
        return factory()
    monkeypatch.setattr(main,'SessionLocal',background_session)
    async def connected(): return False
    async def no_sleep(_): pass
    monkeypatch.setattr(main.asyncio,'sleep',no_sleep)
    request=SimpleNamespace(headers={},cookies={'hutano_session':create_session_token(user)},is_disconnected=connected)
    response=await main.events(request,user,cursor=str(records[0].id))
    iterator=response.body_iterator
    messages=[]
    while len(messages)<105:
        message=await anext(iterator)
        if message.startswith('id: '): messages.append(message)
    assert len(set(messages)) == 105 and all('private' not in item for item in messages)
    assert str(records[-1].id) in messages[-1]
    with factory() as db:
        revoked=db.get(User,user.id);revoked.session_version+=1;db.commit()
    assert await anext(iterator) == ': keepalive\n\n'
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)
