"""Regression cases for clinical authority, retry safety and explicit state changes."""
import uuid
from datetime import datetime
from sqlalchemy import select
from app.models import AuditEvent, IdempotencyRecord, ServiceEpisode, Visit
from conftest import command_headers, login
from test_workflow import create_registered_visit


def command(client, csrf, path, payload, key=None):
    return client.post('/api/v1' + path, json=payload, headers=command_headers(csrf, key or str(uuid.uuid4())))


def ready(client, urgency='P3', escalation=False):
    csrf = login(client, 'reception@test.local')
    visit = create_registered_visit(client, csrf)
    csrf = login(client, 'clinician@test.local')
    result = command(client, csrf, f"/visits/{visit['id']}/triage", {
        'version': visit['version'], 'configured_urgency': urgency, 'escalation_required': escalation})
    assert result.status_code == 201, result.text
    return csrf, client.get(f"/api/v1/visits/{visit['id']}").json()


def queue(client, visit):
    ep = next(ep for ep in visit['episodes'] if ep['service_type'] == 'consultation')
    return client.get(f"/api/v1/service-points/{ep['service_point_id']}/queue").json()['entries']


def test_changed_payload_cannot_reuse_key(client):
    csrf = login(client, 'reception@test.local')
    assert command(client, csrf, '/patients', {'pseudonym':'First'}, 'one-request-key').status_code == 201
    assert command(client, csrf, '/patients', {'pseudonym':'Changed'}, 'one-request-key').status_code == 409


def test_visit_receipt_replay_secret_not_stored(client, db_session):
    csrf = login(client, 'reception@test.local')
    patient = command(client, csrf, '/patients', {}).json()
    payload = {'patient_id':patient['id']}
    first = command(client, csrf, '/visits', payload, 'visit-receipt-key')
    second = command(client, csrf, '/visits', payload, 'visit-receipt-key')
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    record = db_session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key == 'visit-receipt-key'))
    assert 'opaque_status_token' not in record.response_json
    assert command(client, csrf, '/visits', payload).status_code == 409


def test_unassessed_has_no_fabricated_priority(client):
    csrf = login(client, 'reception@test.local')
    visit = create_registered_visit(client, csrf)
    points = client.get('/api/v1/service-points').json()
    point = next(p for p in points if p['type'] == 'triage')
    entries = client.get(f"/api/v1/service-points/{point['id']}/queue").json()['entries']
    assert entries[0]['confirmed_urgency'] is None


def test_no_model_manual_workflow_and_research_isolation(client):
    csrf, visit = ready(client)
    before = queue(client, visit)
    result = command(client, csrf, f"/visits/{visit['id']}/recommendation", {'features':{}})
    assert result.status_code == 201 and result.json()['available'] is False
    assert queue(client, visit) == before
    login(client, 'research@test.local')
    assert client.get('/api/v1/visits').status_code == 403
    assert client.get('/api/v1/patients').status_code == 403
    assert client.get(f"/api/v1/visits/{visit['id']}").status_code == 403


def test_queue_order_pins_and_stale_reassessment(client):
    _, low = ready(client, 'P5')
    csrf, high = ready(client, 'P2')
    entries = queue(client, high)
    assert [e['visit_id'] for e in entries] == [high['id'],low['id']]
    low_entry = entries[1]
    payload = {'queue_entry_id':low_entry['queue_entry_id'], 'version':low_entry['version'], 'new_rank':1, 'reason_code':'CLINICAL_JUDGEMENT'}
    assert command(client, csrf, '/queue/override', payload).status_code == 200
    entries = queue(client, high)
    assert entries[0]['visit_id'] == low['id'] and entries[0]['manual_pin']
    response = command(client, csrf, f"/visits/{low['id']}/reassess", {'version':low['version'], 'configured_urgency':'P4','reason':'Clinician re-evaluated'})
    assert response.status_code == 200
    assert queue(client, high)[0]['manual_pin']
    assert command(client, csrf, f"/visits/{low['id']}/reassess", {'version':low['version'], 'configured_urgency':'P3','reason':'Stale reassessment'}).status_code == 409


def test_escalation_requires_explicit_resolution(client):
    csrf, visit = ready(client, 'P1', True)
    assert queue_empty_or_absent(visit)
    bad = command(client, csrf, f"/visits/{visit['id']}/reassess", {'version':visit['version'], 'configured_urgency':'P2','reason':'Clinician reassessment'})
    assert bad.status_code == 409
    result = command(client, csrf, f"/visits/{visit['id']}/reassess", {'version':visit['version'], 'configured_urgency':'P2','reason':'Clinician cleared escalation','action':'RESOLVE_ESCALATION'})
    assert result.status_code == 200
    detail = client.get(f"/api/v1/visits/{visit['id']}").json()
    assert len(queue(client, detail)) == 1


def queue_empty_or_absent(visit):
    return not any(ep['service_type'] == 'consultation' for ep in visit['episodes'])


def test_pause_resume_preserves_start_and_correction_preserves_original(client, db_session):
    csrf, visit = ready(client)
    entry = queue(client,visit)[0]
    called = command(client,csrf,f"/queue/{entry['queue_entry_id']}/call",{'version':entry['version']})
    assert called.status_code == 200
    detail = client.get(f"/api/v1/visits/{visit['id']}").json()
    ep = detail['episodes'][-1]
    started = command(client,csrf,f"/episodes/{ep['id']}/start",{'version':ep['version']}).json()
    paused = command(client,csrf,f"/episodes/{ep['id']}/state",{'version':started['version'],'action':'PAUSE','reason':'Demo staff break'}).json()
    resumed = command(client,csrf,f"/episodes/{ep['id']}/start",{'version':paused['version']})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()['started_at'] == started['started_at']
    done = command(client,csrf,f"/episodes/{ep['id']}/complete",{'version':resumed.json()['version']}).json()
    original = client.get(f"/api/v1/visits/{visit['id']}").json()['episodes'][-1]
    correction = command(client,csrf,f"/episodes/{ep['id']}/corrections",{'version':done['version'], 'timestamps':{'called_at':original['queued_at']},'reason':'Reviewed synthetic timing correction'})
    assert correction.status_code == 201, correction.text
    corrected = client.get(f"/api/v1/visits/{visit['id']}").json()['episodes'][-1]
    assert corrected['called_at'] == original['called_at']
    assert len(corrected['corrections']) == 1
    assert command(client,csrf,f"/episodes/{ep['id']}/start",{'version':done['version']}).status_code == 409


def test_outage_blocks_calls_without_removing_queue(client):
    csrf, visit = ready(client)
    entry = queue(client,visit)[0]
    point = next(p for p in client.get('/api/v1/service-points').json() if p['type']=='consultation')
    off = command(client,csrf,f"/service-points/{point['id']}/availability",{'version':point['version'],'capacity':0,'outage_state':'UNAVAILABLE','reason':'Room unavailable'})
    assert off.status_code == 200
    assert command(client,csrf,f"/queue/{entry['queue_entry_id']}/call",{'version':entry['version']}).status_code == 409
    assert len(queue(client,visit)) == 1


def test_logout_revokes_copied_cookie(client):
    csrf = login(client, 'reception@test.local')
    session = client.cookies.get('hutano_session')
    assert client.post('/api/v1/auth/logout', headers={'X-CSRF-Token':csrf}).status_code == 200
    assert client.get('/api/v1/me', headers={'Cookie':f'hutano_session={session}'}).status_code == 401


def test_admin_is_not_implicitly_a_clinician(client):
    csrf, visit = ready(client)
    csrf = login(client,'admin@test.local')
    assert command(client,csrf,f"/visits/{visit['id']}/reassess",{'version':visit['version'],'configured_urgency':'P1','reason':'Forbidden administrator change'}).status_code == 403
