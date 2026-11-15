import uuid

from sqlalchemy import select

from app.models import Facility, Patient, Visit
from app.security import token_digest
from conftest import command_headers, login
from test_workflow import create_registered_visit


def test_public_status_is_minimal(client):
    csrf = login(client, "reception@test.local")
    visit = create_registered_visit(client, csrf, "Private Synthetic Name")
    response = client.post("/api/v1/patient-status/lookup", json={"token": visit["opaque_status_token"]})
    assert response.status_code == 200
    text = response.text.lower()
    assert "private synthetic name" not in text
    assert "urgency" not in text
    assert set(response.json()) == {"token", "stage", "status", "people_ahead", "estimated_wait", "updated_at", "research_notice"}
    assert client.post("/api/v1/patient-status/lookup", json={"token": "A-001.this-is-a-wrong-private-token"}).status_code == 404


def test_cross_facility_visit_is_hidden(client, db_session):
    other = db_session.scalar(select(Facility).where(Facility.name == "Other Demo Clinic"))
    patient = Patient(facility_id=other.id, pseudonym="Other facility", synthetic_flag=True)
    db_session.add(patient); db_session.flush()
    visit = Visit(facility_id=other.id, patient_id=patient.id, public_token="O-001", token_secret_hash=token_digest("other-private-secret-token-123"), status="REGISTERING", planned_services=[])
    db_session.add(visit); db_session.commit()
    login(client, "admin@test.local")
    assert client.get(f"/api/v1/visits/{visit.id}").status_code == 404


def test_queue_entry_cannot_be_called_twice(client):
    reception = login(client, "reception@test.local")
    visit = create_registered_visit(client, reception)
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": reception})
    clinician = login(client, "clinician@test.local")
    client.post(f"/api/v1/visits/{visit['id']}/triage", json={"configured_urgency": "P3", "reason": "Test", "observations": {}, "escalation_required": False, "recommendation_decision": "NO_MODEL", "version": visit["version"]}, headers=command_headers(clinician, "triage-call-test"))
    detail = client.get(f"/api/v1/visits/{visit['id']}").json()
    consultation = next(item for item in detail["episodes"] if item["service_type"] == "consultation")
    entry = client.get(f"/api/v1/service-points/{consultation['service_point_id']}/queue").json()["entries"][0]
    first = client.post(f"/api/v1/queue/{entry['queue_entry_id']}/call", json={"version": entry["version"]}, headers=command_headers(clinician, "first-call"))
    second = client.post(f"/api/v1/queue/{entry['queue_entry_id']}/call", json={"version": entry["version"]}, headers=command_headers(clinician, "second-call"))
    assert first.status_code == 200
    assert second.status_code == 409


def test_escalation_is_not_routine_queued(client):
    reception = login(client, "reception@test.local")
    visit = create_registered_visit(client, reception)
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": reception})
    clinician = login(client, "clinician@test.local")
    response = client.post(f"/api/v1/visits/{visit['id']}/triage", json={"configured_urgency": "P1", "reason": "Immediate clinician direction", "observations": {}, "escalation_required": True, "recommendation_decision": "NO_MODEL", "version": visit["version"]}, headers=command_headers(clinician, "triage-escalation"))
    assert response.json()["status"] == "ESCALATION_REQUIRED"
    detail = client.get(f"/api/v1/visits/{visit['id']}").json()
    assert not any(item["service_type"] == "consultation" for item in detail["episodes"])


def test_audit_has_no_observations(client):
    reception = login(client, "reception@test.local")
    visit = create_registered_visit(client, reception)
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": reception})
    clinician = login(client, "clinician@test.local")
    secret_value = "sensitive-observation-value"
    client.post(f"/api/v1/visits/{visit['id']}/triage", json={"configured_urgency": "P4", "reason": "Recorded assessment", "observations": {"demo_field": secret_value}, "escalation_required": False, "recommendation_decision": "NO_MODEL", "version": visit["version"]}, headers=command_headers(clinician, "triage-observation"))
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": clinician})
    research = login(client, "research@test.local")
    audit = client.get("/api/v1/audit")
    assert audit.status_code == 200
    assert audit.json()
    assert secret_value not in audit.text


def test_rbac_capacity(client):
    csrf = login(client, "reception@test.local")
    point = client.get("/api/v1/service-points").json()[0]
    response = client.post(f"/api/v1/service-points/{point['id']}/availability", json={"capacity": 0, "outage_state": "UNAVAILABLE", "reason": "test", "version": point["version"]}, headers=command_headers(csrf, "capacity-forbidden"))
    assert response.status_code == 403

