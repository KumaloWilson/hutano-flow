import uuid

from conftest import command_headers, login


def create_registered_visit(client, csrf: str, name: str = "Synthetic A"):
    patient = client.post(
        "/api/v1/patients",
        json={"pseudonym": name, "age_band": "adult", "sex": "not_recorded", "synthetic_flag": True},
        headers=command_headers(csrf, f"patient-{uuid.uuid4()}"),
    )
    assert patient.status_code == 201, patient.text
    visit = client.post(
        "/api/v1/visits",
        json={"patient_id": patient.json()["id"], "visit_type": "walk_in", "planned_services": ["triage", "consultation", "pharmacy"]},
        headers=command_headers(csrf, f"visit-{uuid.uuid4()}"),
    )
    assert visit.status_code == 201, visit.text
    body = visit.json()
    registered = client.post(
        f"/api/v1/visits/{body['id']}/register",
        json={"version": body["version"]},
        headers=command_headers(csrf, f"register-{uuid.uuid4()}"),
    )
    assert registered.status_code == 200, registered.text
    body["version"] = registered.json()["version"]
    body["status"] = "AWAITING_TRIAGE"
    return body


def test_complete_walk_in_journey(client):
    reception_csrf = login(client, "reception@test.local")
    visit = create_registered_visit(client, reception_csrf)
    opaque = visit["opaque_status_token"]
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": reception_csrf})

    clinician_csrf = login(client, "clinician@test.local")
    triage = client.post(
        f"/api/v1/visits/{visit['id']}/triage",
        json={"configured_urgency": "P2", "reason": "Clinician demo assessment", "observations": {}, "escalation_required": False, "recommendation_decision": "NO_MODEL", "version": visit["version"]},
        headers=command_headers(clinician_csrf, "triage-one"),
    )
    assert triage.status_code == 201, triage.text
    detail = client.get(f"/api/v1/visits/{visit['id']}").json()
    consultation = next(ep for ep in detail["episodes"] if ep["service_type"] == "consultation")
    queue = client.get(f"/api/v1/service-points/{consultation['service_point_id']}/queue").json()["entries"]
    entry = next(item for item in queue if item["visit_id"] == visit["id"])
    called = client.post(f"/api/v1/queue/{entry['queue_entry_id']}/call", json={"version": entry["version"]}, headers=command_headers(clinician_csrf, "call-consult"))
    assert called.status_code == 200
    detail = client.get(f"/api/v1/visits/{visit['id']}").json()
    consultation = next(ep for ep in detail["episodes"] if ep["service_type"] == "consultation")
    started = client.post(f"/api/v1/episodes/{consultation['id']}/start", json={"version": consultation["version"]}, headers=command_headers(clinician_csrf, "start-consult"))
    assert started.status_code == 200, started.text
    completed = client.post(f"/api/v1/episodes/{consultation['id']}/complete", json={"version": started.json()["version"], "next_service_type": "pharmacy"}, headers=command_headers(clinician_csrf, "complete-consult"))
    assert completed.status_code == 200, completed.text
    detail = client.get(f"/api/v1/visits/{visit['id']}").json()
    pharmacy = next(ep for ep in detail["episodes"] if ep["service_type"] == "pharmacy")
    clinician_csrf = login(client, "pharmacy@test.local")
    point_queue = client.get(f"/api/v1/service-points/{pharmacy['service_point_id']}/queue").json()["entries"]
    pharmacy_entry = next(item for item in point_queue if item["visit_id"] == visit["id"])
    called = client.post(f"/api/v1/queue/{pharmacy_entry['queue_entry_id']}/call", json={"version": pharmacy_entry["version"]}, headers=command_headers(clinician_csrf, "call-pharmacy"))
    detail = client.get(f"/api/v1/visits/{visit['id']}").json()
    pharmacy = next(ep for ep in detail["episodes"] if ep["service_type"] == "pharmacy")
    started = client.post(f"/api/v1/episodes/{pharmacy['id']}/start", json={"version": pharmacy["version"]}, headers=command_headers(clinician_csrf, "start-pharmacy"))
    completed = client.post(f"/api/v1/episodes/{pharmacy['id']}/complete", json={"version": started.json()["version"], "next_service_type": None}, headers=command_headers(clinician_csrf, "complete-pharmacy"))
    assert completed.json()["visit_status"] == "COMPLETED"
    public = client.post("/api/v1/patient-status/lookup", json={"token": opaque})
    assert public.status_code == 200
    assert public.json()["status"] == "COMPLETED"


def test_receptionist_cannot_triage(client):
    csrf = login(client, "reception@test.local")
    visit = create_registered_visit(client, csrf)
    response = client.post(
        f"/api/v1/visits/{visit['id']}/triage",
        json={"configured_urgency": "P1", "observations": {}, "escalation_required": False, "recommendation_decision": "NO_MODEL", "version": visit["version"]},
        headers=command_headers(csrf, "forbidden-triage"),
    )
    assert response.status_code == 403


def test_idempotent_patient_creation(client):
    csrf = login(client, "reception@test.local")
    payload = {"pseudonym": "Same command", "synthetic_flag": True}
    headers = command_headers(csrf, "repeat-patient-key")
    first = client.post("/api/v1/patients", json=payload, headers=headers)
    second = client.post("/api/v1/patients", json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_csrf_required(client):
    login(client, "reception@test.local")
    response = client.post("/api/v1/patients", json={"pseudonym": "Blocked", "synthetic_flag": True}, headers={"Idempotency-Key": "csrf-blocked"})
    assert response.status_code == 403

