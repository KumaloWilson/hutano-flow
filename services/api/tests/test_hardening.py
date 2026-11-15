"""Regression tests for the November 2026 hardening pass (ADR-027 .. ADR-031)."""
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent, DayClosure, QueueEntry, User, Visit, utcnow
from app.security import client_ip, create_session_token, decode_session_token
from conftest import command_headers, login
from test_workflow import create_registered_visit

PROXY = ("172.18.0.5", 41000)  # the web container on the Compose network


def proxied(ip: str) -> dict:
    return {"X-Forwarded-For": ip}


def triaged_to_consultation(client, name="Synthetic Q", urgency="P3"):
    """Registered by reception, triaged by a clinician; returns (visit, entry, clinician_csrf)."""
    csrf = login(client, "reception@test.local")
    visit = create_registered_visit(client, csrf, name)
    client.cookies.clear()
    csrf = login(client, "clinician@test.local")
    triage = client.post(f"/api/v1/visits/{visit['id']}/triage", json={
        "configured_urgency": urgency, "reason": "Synthetic assessment", "observations": {}, "escalation_required": False,
        "recommendation_decision": "NO_MODEL", "version": visit["version"]}, headers=command_headers(csrf, str(uuid.uuid4())))
    assert triage.status_code == 201, triage.text
    detail = client.get(f"/api/v1/visits/{visit['id']}").json()
    consult = next(ep for ep in detail["episodes"] if ep["service_type"] == "consultation")
    entries = client.get(f"/api/v1/service-points/{consult['service_point_id']}/queue").json()["entries"]
    return visit, next(e for e in entries if e["visit_id"] == visit["id"]), csrf, consult["service_point_id"]


def episode(client, visit_id, service="consultation"):
    return next(ep for ep in client.get(f"/api/v1/visits/{visit_id}").json()["episodes"] if ep["service_type"] == service)


# ----------------------------------------------------------------- client address


def fake_request(peer, forwarded=None):
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_client_ip_trusts_forwarded_header_only_from_proxy():
    assert client_ip(fake_request("172.18.0.5", "41.60.1.9")) == "41.60.1.9"
    # A client-supplied hop is ignored: Next.js appends the real address to the right.
    assert client_ip(fake_request("172.18.0.5", "1.2.3.4, 41.60.1.9")) == "41.60.1.9"
    # Caddy -> Next.js -> API: skip trusted hops from the right.
    assert client_ip(fake_request("172.18.0.5", "41.60.1.9, 172.18.0.7")) == "41.60.1.9"
    # A direct, untrusted peer cannot choose its bucket.
    assert client_ip(fake_request("41.60.1.9", "8.8.8.8")) == "41.60.1.9"


def test_waiting_room_polling_through_proxy_is_not_throttled(db_session):
    """The bug: every request arrived from the web container, so 4 polling patients hit 429."""
    with TestClient(app, client=PROXY) as client:
        csrf = login(client, "reception@test.local")
        tokens = [create_registered_visit(client, csrf, f"Synthetic {i}")["opaque_status_token"] for i in range(6)]
        client.cookies.clear()
        # Six patients, ~1.5 minutes of 10-second polling each, on separate phones.
        for _ in range(9):
            for index, token in enumerate(tokens):
                response = client.post("/api/v1/patient-status/lookup", json={"token": token}, headers=proxied(f"41.60.2.{index}"))
                assert response.status_code == 200, response.text


def test_waiting_room_behind_one_nat_is_not_throttled(db_session):
    with TestClient(app, client=PROXY) as client:
        csrf = login(client, "reception@test.local")
        tokens = [create_registered_visit(client, csrf, f"Synthetic {i}")["opaque_status_token"] for i in range(8)]
        client.cookies.clear()
        for _ in range(6):
            for token in tokens:
                assert client.post("/api/v1/patient-status/lookup", json={"token": token}, headers=proxied("41.60.3.3")).status_code == 200


def test_token_guessing_is_still_limited_per_real_address(db_session):
    with TestClient(app, client=PROXY) as client:
        for _ in range(20):
            assert client.post("/api/v1/patient-status/lookup", json={"token": "A-001.guess-guess-guess-guess"},
                               headers=proxied("41.60.4.4")).status_code == 404
        assert client.post("/api/v1/patient-status/lookup", json={"token": "A-001.guess-guess-guess-guess"},
                           headers=proxied("41.60.4.4")).status_code == 429
        # A different patient's phone is unaffected.
        assert client.post("/api/v1/patient-status/lookup", json={"token": "A-002.another-mistyped-token"},
                           headers=proxied("41.60.4.5")).status_code == 404


def test_one_bad_typist_does_not_lock_out_the_whole_clinic(db_session):
    with TestClient(app, client=PROXY) as client:
        for _ in range(30):
            client.post("/api/v1/auth/login", json={"email": "nobody@test.local", "password": "Wrong-password-1"}, headers=proxied("41.60.5.5"))
        ok = client.post("/api/v1/auth/login", json={"email": "reception@test.local", "password": "Testing123!"}, headers=proxied("41.60.5.6"))
        assert ok.status_code == 200, ok.text


# ------------------------------------------------------------------ authentication


def test_unknown_email_pays_the_same_password_cost(client, monkeypatch):
    calls = []
    import app.main as main
    monkeypatch.setattr(main, "burn_password_check", lambda password: calls.append(password))
    response = client.post("/api/v1/auth/login", json={"email": "ghost@test.local", "password": "Whatever-123"})
    assert response.status_code == 401 and calls == ["Whatever-123"]


def test_account_locks_after_consecutive_failures_and_admin_unlocks(client, db_session):
    for _ in range(4):
        assert client.post("/api/v1/auth/login", json={"email": "reception@test.local", "password": "Wrong-password-1"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "reception@test.local", "password": "Wrong-password-1"}).status_code == 429
    # Even the correct password is refused while locked.
    locked = client.post("/api/v1/auth/login", json={"email": "reception@test.local", "password": "Testing123!"})
    assert locked.status_code == 429 and "Retry-After" in locked.headers
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.action == "auth.account_locked")) is not None
    csrf = login(client, "admin@test.local")
    target = next(u for u in client.get("/api/v1/admin/users").json() if u["email"] == "reception@test.local")
    assert target["locked"] is True
    unlocked = client.post(f"/api/v1/admin/users/{target['id']}", json={"roles": ["RECEPTIONIST"], "active": True},
                           headers=command_headers(csrf, str(uuid.uuid4())))
    assert unlocked.status_code == 200
    client.cookies.clear()
    login(client, "reception@test.local")


def test_successful_login_resets_failure_count(client, db_session):
    for _ in range(4):
        client.post("/api/v1/auth/login", json={"email": "reception@test.local", "password": "Wrong-password-1"})
    login(client, "reception@test.local")
    client.cookies.clear()
    for _ in range(4):
        assert client.post("/api/v1/auth/login", json={"email": "reception@test.local", "password": "Wrong-password-1"}).status_code == 401


def test_temporary_password_must_be_changed_before_any_work(client, db_session):
    csrf = login(client, "admin@test.local")
    weak = client.post("/api/v1/admin/users", json={"email": "new@test.local", "display_name": "New Nurse", "password": "password1234", "roles": ["TRIAGE_NURSE"]},
                       headers=command_headers(csrf, str(uuid.uuid4())))
    assert weak.status_code == 422
    created = client.post("/api/v1/admin/users", json={"email": "new@test.local", "display_name": "New Nurse", "password": "Temporary-Pass-2026", "roles": ["TRIAGE_NURSE"]},
                          headers=command_headers(csrf, str(uuid.uuid4())))
    assert created.status_code == 201, created.text
    client.cookies.clear()
    signed = client.post("/api/v1/auth/login", json={"email": "new@test.local", "password": "Temporary-Pass-2026"})
    assert signed.status_code == 200 and signed.json()["user"]["must_change_password"] is True
    csrf = signed.json()["csrf_token"]
    assert client.get("/api/v1/visits").status_code == 403
    assert client.get("/api/v1/me").status_code == 200
    rejected = client.post("/api/v1/auth/password", json={"current_password": "Temporary-Pass-2026", "new_password": "NewNurse-at-clinic-1"},
                           headers={"X-CSRF-Token": csrf})
    assert rejected.status_code == 422
    changed = client.post("/api/v1/auth/password", json={"current_password": "Temporary-Pass-2026", "new_password": "Kopje sunrise over Mutare"},
                          headers={"X-CSRF-Token": csrf})
    assert changed.status_code == 200, changed.text
    assert changed.json()["user"]["must_change_password"] is False
    assert client.get("/api/v1/visits").status_code == 200


def test_password_change_signs_out_other_devices(db_session):
    with TestClient(app) as phone, TestClient(app) as desk:
        login(phone, "reception@test.local")
        csrf = login(desk, "reception@test.local")
        assert desk.post("/api/v1/auth/password", json={"current_password": "Testing123!", "new_password": "Long enough passphrase 9"},
                         headers={"X-CSRF-Token": csrf}).status_code == 200
        assert phone.get("/api/v1/me").status_code == 401
        assert desk.get("/api/v1/me").status_code == 200


def test_admin_password_reset_forces_change_and_revokes(client, db_session):
    csrf = login(client, "admin@test.local")
    target = next(u for u in client.get("/api/v1/admin/users").json() if u["email"] == "pharmacy@test.local")
    reset = client.post(f"/api/v1/admin/users/{target['id']}/password", json={"temporary_password": "Reset-Temp-Pass-77", "reason": "Forgot password at shift start"},
                        headers=command_headers(csrf, str(uuid.uuid4())))
    assert reset.status_code == 200, reset.text
    user = db_session.scalar(select(User).where(User.email == "pharmacy@test.local"))
    assert user.must_change_password is True


def test_session_idle_window_is_capped_by_absolute_lifetime(db_session):
    from app.config import settings
    user = db_session.scalar(select(User).where(User.email == "reception@test.local"))
    fresh = decode_session_token(create_session_token(user))
    assert fresh["exp"] - fresh["iat"] <= settings.session_idle_minutes * 60 + 1
    old_auth = utcnow() - timedelta(minutes=settings.session_minutes - 2)
    nearly_over = decode_session_token(create_session_token(user, auth_time=old_auth))
    assert nearly_over["exp"] <= int((old_auth + timedelta(minutes=settings.session_minutes)).timestamp()) + 1


def test_refresh_extends_idle_window(client):
    csrf = login(client, "reception@test.local")
    refreshed = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert refreshed.status_code == 200 and "expires_at" in refreshed.json()


def test_like_wildcards_do_not_list_everything(client):
    csrf = login(client, "reception@test.local")
    create_registered_visit(client, csrf, "Synthetic Alpha")
    create_registered_visit(client, csrf, "Synthetic Beta")
    assert client.get("/api/v1/patients", params={"q": "%"}).json() == []
    assert client.get("/api/v1/patients", params={"q": "_"}).json() == []
    assert client.get("/api/v1/visits", params={"q": "%"}).json() == []
    assert len(client.get("/api/v1/patients", params={"q": "Alpha"}).json()) == 1


# ------------------------------------------------------------------- missed calls


def test_recall_keeps_call_and_defer_keeps_place_but_lets_others_go_first(client, db_session):
    first, entry, csrf, point = triaged_to_consultation(client, "Synthetic First")
    client.cookies.clear()
    second, _, csrf, _ = triaged_to_consultation(client, "Synthetic Second")
    called = client.post(f"/api/v1/queue/{entry['queue_entry_id']}/call", json={"version": entry["version"]}, headers=command_headers(csrf, str(uuid.uuid4())))
    assert called.status_code == 200
    ep = episode(client, first["id"])
    recall = client.post(f"/api/v1/episodes/{ep['id']}/state", json={"action": "RECALL", "version": ep["version"], "reason": "No answer at door"},
                         headers=command_headers(csrf, str(uuid.uuid4())))
    assert recall.status_code == 200 and recall.json()["recall_count"] == 1
    ep = episode(client, first["id"])
    assert ep["status"] == "CALLED" and ep["recall_count"] == 1
    original_queued = ep["queued_at"]
    deferred = client.post(f"/api/v1/episodes/{ep['id']}/state", json={"action": "DEFER", "version": ep["version"], "reason": "Not in waiting area", "defer_minutes": 10},
                           headers=command_headers(csrf, str(uuid.uuid4())))
    assert deferred.status_code == 200, deferred.text
    ep = episode(client, first["id"])
    assert ep["status"] == "WAITING" and ep["missed_calls"] == 1 and ep["queued_at"] == original_queued
    entries = client.get(f"/api/v1/service-points/{point}/queue").json()["entries"]
    assert [e["visit_id"] for e in entries] == [second["id"], first["id"]]
    assert entries[1]["deferred_until"] is not None
    # Once the grace period ends, their original place is restored.
    row = db_session.get(QueueEntry, uuid.UUID(entries[1]["queue_entry_id"]))
    row.deferred_until = utcnow() - timedelta(minutes=1)
    db_session.commit()
    entries = client.get(f"/api/v1/service-points/{point}/queue").json()["entries"]
    assert entries[0]["visit_id"] == first["id"]


def test_defer_is_limited_to_three_missed_calls(client, db_session):
    visit, entry, csrf, point = triaged_to_consultation(client)
    for attempt in range(4):
        entry = client.get(f"/api/v1/service-points/{point}/queue").json()["entries"][0]
        assert client.post(f"/api/v1/queue/{entry['queue_entry_id']}/call", json={"version": entry["version"]},
                           headers=command_headers(csrf, str(uuid.uuid4()))).status_code == 200
        ep = episode(client, visit["id"])
        response = client.post(f"/api/v1/episodes/{ep['id']}/state", json={"action": "DEFER", "version": ep["version"], "reason": "Not present"},
                               headers=command_headers(csrf, str(uuid.uuid4())))
        if attempt < 3:
            assert response.status_code == 200
        else:
            assert response.status_code == 409 and "no-show" in response.json()["error"]


def test_recall_requires_a_called_patient(client):
    visit, entry, csrf, _ = triaged_to_consultation(client)
    ep = episode(client, visit["id"])
    assert client.post(f"/api/v1/episodes/{ep['id']}/state", json={"action": "RECALL", "version": ep["version"], "reason": "Recall"},
                       headers=command_headers(csrf, str(uuid.uuid4()))).status_code == 409


# ---------------------------------------------------------------------- day close


def test_day_close_records_unseen_patients_without_deleting_history(client, db_session):
    visit, entry, _, point = triaged_to_consultation(client)
    client.cookies.clear()
    reception = login(client, "reception@test.local")
    waiting_registration = create_registered_visit(client, reception, "Synthetic Late")
    assert client.get("/api/v1/operations/day-close").status_code == 403
    client.cookies.clear()
    csrf = login(client, "admin@test.local")
    preview = client.get("/api/v1/operations/day-close").json()
    assert preview["open_count"] == 2 and preview["blocking_count"] == 0
    assert "pseudonym" not in str(preview)
    stale = client.post("/api/v1/operations/day-close", json={"local_date": preview["local_date"], "reason": "End of clinic day", "expected_open_count": 1},
                        headers=command_headers(csrf, str(uuid.uuid4())))
    assert stale.status_code == 409
    closed = client.post("/api/v1/operations/day-close", json={"local_date": preview["local_date"], "reason": "End of clinic day", "expected_open_count": 2},
                         headers=command_headers(csrf, str(uuid.uuid4())))
    assert closed.status_code == 201, closed.text
    assert closed.json()["closed_unseen"] == 2
    for visit_id in (visit["id"], waiting_registration["id"]):
        detail = client.get(f"/api/v1/visits/{visit_id}").json()
        assert detail["status"] == "LEFT_WITHOUT_SERVICE"
        assert all(ep["status"] in {"COMPLETED", "CANCELLED"} for ep in detail["episodes"])
    assert client.get(f"/api/v1/service-points/{point}/queue").json()["entries"] == []
    assert db_session.scalar(select(DayClosure)) is not None
    again = client.post("/api/v1/operations/day-close", json={"local_date": preview["local_date"], "reason": "End of clinic day", "expected_open_count": 0},
                        headers=command_headers(csrf, str(uuid.uuid4())))
    assert again.status_code == 409


def test_day_close_refuses_to_drop_a_patient_in_service(client):
    visit, entry, csrf, _ = triaged_to_consultation(client)
    client.post(f"/api/v1/queue/{entry['queue_entry_id']}/call", json={"version": entry["version"]}, headers=command_headers(csrf, str(uuid.uuid4())))
    ep = episode(client, visit["id"])
    assert client.post(f"/api/v1/episodes/{ep['id']}/start", json={"version": ep["version"]}, headers=command_headers(csrf, str(uuid.uuid4()))).status_code == 200
    preview = client.get("/api/v1/operations/day-close").json()
    assert preview["blocking_count"] == 1
    body = {"local_date": preview["local_date"], "reason": "End of clinic day", "expected_open_count": 1}
    assert client.post("/api/v1/operations/day-close", json=body, headers=command_headers(csrf, str(uuid.uuid4()))).status_code == 409
    kept = client.post("/api/v1/operations/day-close", json={**body, "keep_open": [visit["id"]]}, headers=command_headers(csrf, str(uuid.uuid4())))
    assert kept.status_code == 201 and kept.json()["kept_open"] == 1
    assert episode(client, visit["id"])["status"] == "IN_SERVICE"


def test_entries_from_an_earlier_day_are_flagged(client, db_session):
    visit, entry, _, point = triaged_to_consultation(client)
    row = db_session.get(QueueEntry, uuid.UUID(entry["queue_entry_id"]))
    row.joined_at = utcnow() - timedelta(days=1, hours=2)
    db_session.commit()
    flagged = client.get(f"/api/v1/service-points/{point}/queue").json()["entries"][0]
    assert flagged["carried_over"] is True and "earlier day" in flagged["explanations"][0]


# -------------------------------------------------------------- downtime back-entry


def retro_body(patient_id, start):
    iso = lambda minutes: (start + timedelta(minutes=minutes)).isoformat()
    return {"patient_id": patient_id, "arrival_at": iso(0), "paper_reference": "Downtime sheet 14/11 #3", "reason": "Network outage morning",
            "outcome": "COMPLETED", "stages": [
                {"service_type": "registration", "queued_at": iso(0), "started_at": iso(2), "ended_at": iso(5)},
                {"service_type": "triage", "queued_at": iso(5), "started_at": iso(20), "ended_at": iso(28)},
                {"service_type": "consultation", "queued_at": iso(28), "started_at": iso(70), "ended_at": iso(85)}]}


def test_paper_downtime_visit_is_back_entered_and_labelled(client, db_session):
    csrf = login(client, "reception@test.local")
    patient = client.post("/api/v1/patients", json={"pseudonym": "Synthetic Paper", "synthetic_flag": True}, headers=command_headers(csrf, str(uuid.uuid4()))).json()
    start = utcnow() - timedelta(hours=6)
    created = client.post("/api/v1/operations/retrospective-visits", json=retro_body(patient["id"], start), headers=command_headers(csrf, str(uuid.uuid4())))
    assert created.status_code == 201, created.text
    assert created.json()["public_token"].startswith("P-") and created.json()["entry_mode"] == "RETROSPECTIVE"
    detail = client.get(f"/api/v1/visits/{created.json()['id']}").json()
    assert detail["entry_mode"] == "RETROSPECTIVE" and detail["status"] == "COMPLETED" and len(detail["episodes"]) == 3
    client.cookies.clear()
    login(client, "research@test.local")
    assert client.get("/api/v1/analytics/overview").json()["retrospective_visits"] == 1


def test_back_entry_rejects_impossible_paper_times(client):
    csrf = login(client, "reception@test.local")
    patient = client.post("/api/v1/patients", json={"pseudonym": "Synthetic Paper", "synthetic_flag": True}, headers=command_headers(csrf, str(uuid.uuid4()))).json()
    body = retro_body(patient["id"], utcnow() - timedelta(hours=6))
    body["stages"][1]["queued_at"] = body["stages"][0]["queued_at"]
    assert client.post("/api/v1/operations/retrospective-visits", json=body, headers=command_headers(csrf, str(uuid.uuid4()))).status_code == 422
    future = retro_body(patient["id"], utcnow() + timedelta(hours=1))
    assert client.post("/api/v1/operations/retrospective-visits", json=future, headers=command_headers(csrf, str(uuid.uuid4()))).status_code == 422
    client.cookies.clear()
    clinician = login(client, "clinician@test.local")
    ok_body = retro_body(patient["id"], utcnow() - timedelta(hours=6))
    assert client.post("/api/v1/operations/retrospective-visits", json=ok_body, headers=command_headers(clinician, str(uuid.uuid4()))).status_code == 403


# ------------------------------------------------------------------------ display


def test_display_board_shows_called_numbers_only(client, db_session):
    visit, entry, csrf, _ = triaged_to_consultation(client, "Synthetic Hidden Name", urgency="P1")
    client.post(f"/api/v1/queue/{entry['queue_entry_id']}/call", json={"version": entry["version"]}, headers=command_headers(csrf, str(uuid.uuid4())))
    client.cookies.clear()
    admin = login(client, "admin@test.local")
    key = str(uuid.uuid4())
    created = client.post("/api/v1/admin/display-screens", json={"label": "Main waiting room"}, headers=command_headers(admin, key))
    assert created.status_code == 201
    secret = created.json()["display_key"]
    replay = client.post("/api/v1/admin/display-screens", json={"label": "Main waiting room"}, headers=command_headers(admin, key))
    assert replay.headers.get("Idempotent-Replayed") == "true" and "display_key" not in replay.json()
    client.cookies.clear()
    board = client.post("/api/v1/display/board", json={"key": secret})
    assert board.status_code == 200, board.text
    payload = board.json()
    assert payload["now_calling"][0]["token"] == visit["public_token"]
    text = board.text
    assert "Synthetic Hidden Name" not in text and "P1" not in text and "urgency" not in text
    assert all(set(q) == {"service", "service_type", "waiting", "open"} for q in payload["queues"])
    login(client, "admin@test.local")
    screen_id = created.json()["id"]
    admin = client.cookies["hutano_csrf"]
    assert client.post(f"/api/v1/admin/display-screens/{screen_id}/revoke", json={}, headers=command_headers(admin, str(uuid.uuid4()))).status_code == 200
    client.cookies.clear()
    assert client.post("/api/v1/display/board", json={"key": secret}).status_code == 404


def test_display_screens_are_facility_scoped(client):
    admin = login(client, "admin@test.local")
    created = client.post("/api/v1/admin/display-screens", json={"label": "Pharmacy hall"}, headers=command_headers(admin, str(uuid.uuid4()))).json()
    client.cookies.clear()
    other = login(client, "other@test.local")
    assert client.get("/api/v1/admin/display-screens").json() == []
    assert client.post(f"/api/v1/admin/display-screens/{created['id']}/revoke", json={}, headers=command_headers(other, str(uuid.uuid4()))).status_code == 404


# ------------------------------------------------------------------ health + FHIR


def test_system_health_for_admin_and_manager_only(client):
    login(client, "admin@test.local")
    health = client.get("/api/v1/admin/system-health")
    assert health.status_code == 200
    assert {"database", "worker", "storage", "backup", "security", "operations", "displays"} <= set(health.json()["checks"])
    client.cookies.clear()
    login(client, "research@test.local")
    assert client.get("/api/v1/admin/system-health").status_code == 200
    client.cookies.clear()
    login(client, "reception@test.local")
    assert client.get("/api/v1/admin/system-health").status_code == 403


def test_fhir_bundle_is_structurally_valid_and_minimal(client):
    from app.interop import validate_bundle
    visit, entry, _, _ = triaged_to_consultation(client, "Synthetic Fhir Name")
    client.cookies.clear()
    login(client, "admin@test.local")
    bundle = client.get(f"/api/v1/interop/fhir/Encounter/{visit['id']}").json()
    assert validate_bundle(bundle) == []
    types = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert types[:2] == ["Patient", "Encounter"]
    assert "Synthetic Fhir Name" not in str(bundle)
    encounter = bundle["entry"][1]["resource"]
    assert encounter["class"]["code"] == "AMB" and encounter["priority"]["coding"][0]["code"] == "P3"
    today = utcnow().date().isoformat()
    export = client.get("/api/v1/interop/fhir/export", params={"from_date": today, "to_date": today})
    assert export.status_code == 200 and validate_bundle(export.json()) == []
    client.cookies.clear()
    login(client, "research@test.local")
    assert client.get(f"/api/v1/interop/fhir/Encounter/{visit['id']}").status_code == 403
    client.cookies.clear()
    login(client, "other@test.local")
    assert client.get(f"/api/v1/interop/fhir/Encounter/{visit['id']}").status_code == 404
