"""Research workflows use synthetic cases, never clinical patient mutations."""
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, func

from app.ml.pipeline import generate_synthetic_training_data, train_model, validate_frame
from app.models import (CaseReview, Dataset, Job, ModelVersion, ResearchCase, ResearchProtocol,
                        ResearchStudyRun, ResearchTrial, User, UserRole, Visit)
from app.security import hash_password
from conftest import command_headers, login

BASE = "/api/v1/research/workbench"


@pytest.fixture()
def research_data(db_session, tmp_path):
    user = db_session.scalar(select(User).where(User.email == "research@test.local"))
    frame = generate_synthetic_training_data(count=300)
    raw = frame.to_csv(index=False).encode()
    path = tmp_path / "dataset.csv"; path.write_bytes(raw)
    dataset = Dataset(facility_id=user.facility_id, name="Synthetic workbench test", source_type="SYNTHETIC",
                      dataset_hash=hashlib.sha256(raw).hexdigest(), consent_basis_note="Synthetic verification fixture, not fieldwork",
                      schema_json=validate_frame(frame.copy()), row_count=len(frame), synthetic_flag=True, file_path=str(path))
    db_session.add(dataset)
    second = User(facility_id=user.facility_id, email="reviewer2@test.local", display_name="Second test reviewer",
                  password_hash=hash_password("Testing123!"))
    db_session.add(second); db_session.flush()
    db_session.add(UserRole(user_id=second.id, facility_id=user.facility_id, role="TRIAGE_NURSE"))
    db_session.commit()
    return dataset


def publish(client, csrf, dataset, **extra):
    payload = {"name": "Frozen synthetic verification", "question": "Does uncertainty-aware advice help on independent synthetic cases?",
               "dataset_id": str(dataset.id), "case_count": 12,
               "operations_config": {"training_days": 28, "test_days": 4, "arrivals_per_day": 20, "replications": 2}, **extra}
    r = client.post(BASE+"/protocols", json=payload, headers=command_headers(csrf, str(uuid.uuid4())))
    assert r.status_code == 201, r.text
    return r.json()


def create_model(db, dataset, tmp_path):
    outcome = train_model(generate_synthetic_training_data(count=300), tmp_path / "model")
    clinician = db.scalar(select(User).where(User.email == "clinician@test.local"))
    model = ModelVersion(facility_id=dataset.facility_id, dataset_id=dataset.id, model_name="Test synthetic model",
                         version=outcome["version"], artifact_path=outcome["artifact_path"],
                         feature_schema_hash=outcome["feature_schema_hash"], metrics_json=outcome["metrics"],
                         status="REVIEWED", active=False, reviewed_by=clinician.id, review_note="Synthetic test fixture review only")
    db.add(model); db.commit(); return model


def test_frozen_protocol_blinding_provenance_and_permissions(client, db_session, research_data):
    csrf = login(client, "research@test.local")
    p = publish(client, csrf, research_data)
    assert p["configuration"]["dataset_hash"] == research_data.dataset_hash
    assert p["configuration"]["feature_schema"]["recorded_measurement"]["unit"] == "dimensionless"
    detail = client.get(BASE+f"/protocols/{p['id']}").json()
    assert len(detail["cases"]) == 12
    assert all(c["own_review"] is None and "synthetic_label" not in c for c in detail["cases"])
    case = detail["cases"][0]
    assert client.post(BASE+f"/cases/{case['id']}/reviews", json={"label": "P2", "reason": "Researcher cannot label"}, headers=command_headers(csrf, str(uuid.uuid4()))).status_code == 403
    login(client, "reception@test.local")
    assert client.get(BASE+"/overview").status_code == 403
    login(client, "other@test.local")
    assert client.get(BASE+f"/protocols/{p['id']}").status_code == 404
    assert client.get(BASE+"/overview").json()["protocols"] == []


def test_two_blinded_reviews_consensus_and_no_self_reference_trial(client, db_session, research_data):
    csrf = login(client, "research@test.local"); p = publish(client, csrf, research_data)
    case = client.get(BASE+f"/protocols/{p['id']}").json()["cases"][0]
    csrf = login(client, "clinician@test.local")
    r = client.post(BASE+f"/cases/{case['id']}/reviews", json={"label": "P2", "reason": "Private first reviewer rationale"}, headers=command_headers(csrf, "first-blinded-review"))
    assert r.status_code == 201
    assert client.get(BASE+f"/cases/{case['id']}/adjudication").status_code == 409
    csrf2 = login(client, "reviewer2@test.local")
    blind = client.get(BASE+f"/protocols/{p['id']}").json()["cases"][0]
    assert blind["own_review"] is None and "rationale" not in json.dumps(blind)
    assert client.post(BASE+f"/cases/{case['id']}/reviews", json={"label": "P3", "reason": "Private second reviewer rationale"}, headers=command_headers(csrf2, "second-blinded-review")).status_code == 201
    material = client.get(BASE+f"/cases/{case['id']}/adjudication").json()
    assert [r["label"] for r in material["reviews"]] == ["P2", "P3"]
    assert client.post(BASE+f"/cases/{case['id']}/adjudication", json={"label": "P2", "reason": "Consensus, not clinical gold standard"}, headers=command_headers(csrf2, "consensus-review")).status_code == 201
    trial = client.post(BASE+f"/protocols/{p['id']}/trials/start", json={"consented": True, "consent_ref": "SYNTHETIC_TEST_ONLY"}, headers=command_headers(csrf2, "trial-after-review"))
    assert trial.status_code == 201, trial.text
    assert trial.json()["case_id"] != case["id"] and trial.json()["advisory"] is None
    complete = client.post(BASE+f"/trials/{trial.json()['id']}/complete", json={"label": "P1", "reason": "Private trial reason", "understands_authority": False, "trust_rating": 2}, headers=command_headers(csrf2, "finish-trial-fixture"))
    assert complete.status_code == 200 and complete.json()["elapsed_seconds"] >= 0
    assert client.post(BASE+f"/trials/{trial.json()['id']}/complete", json={"label": "P1", "reason": "Private trial reason", "understands_authority": False, "trust_rating": 2}, headers=command_headers(csrf2, "changed-finish-command")).status_code == 409
    assert client.post(BASE+f"/cases/{trial.json()['case_id']}/reviews", json={"label": "P2", "reason": "Previously exposed case"}, headers=command_headers(csrf2, "contaminated-reference")).status_code == 409
    csrf = login(client, "research@test.local")
    exported = client.get(BASE+f"/protocols/{p['id']}/export").json()
    assert exported["summary"]["paired_cases"] == 1 and exported["summary"]["adjudicated_cases"] == 1
    assert exported["summary"]["arms"][0]["authority_comprehension_rate"] == 0
    text = json.dumps(exported)
    assert "SYNTHETIC_TEST_ONLY" not in text and "Private trial reason" not in text and "reviewer2@test.local" not in text
    assert client.get(BASE+f"/protocols/{p['id']}/export?format=csv").status_code == 200


def test_shadow_prediction_is_hidden_until_independent_response(client, db_session, research_data, tmp_path):
    model = create_model(db_session, research_data, tmp_path)
    csrf = login(client, "research@test.local")
    p = publish(client, csrf, research_data, design="SHADOW", model_id=str(model.id))
    csrf = login(client, "clinician@test.local")
    url = BASE+f"/protocols/{p['id']}/trials/start"
    start = client.post(url, json={"consented": True, "consent_ref": "SHADOW_TEST_FIXTURE"}, headers=command_headers(csrf, "shadow-start-first"))
    assert start.status_code == 201, start.text
    t = start.json(); assert t["advisory"] is None and t["arm"] == "SHADOW"
    assert client.get(BASE+f"/protocols/{p['id']}").json()["trials"][0]["advisory"] is None
    replay = client.post(url, json={"consented": True, "consent_ref": "SHADOW_TEST_FIXTURE"}, headers=command_headers(csrf, "shadow-start-first"))
    assert replay.json()["id"] == t["id"]
    second = client.post(url, json={"consented": True, "consent_ref": "SHADOW_TEST_FIXTURE"}, headers=command_headers(csrf, "shadow-resume-existing"))
    assert second.json()["id"] == t["id"]
    csrf2 = login(client, "reviewer2@test.local")
    assert client.post(BASE+f"/trials/{t['id']}/complete", json={"label": "P2", "reason": "Another user cannot submit", "understands_authority": True, "trust_rating": 3}, headers=command_headers(csrf2, "wrong-participant-trial")).status_code == 404
    csrf = login(client, "clinician@test.local")
    finished = client.post(BASE+f"/trials/{t['id']}/complete", json={"label": "P2", "reason": "Independent before reveal", "understands_authority": True, "trust_rating": 3}, headers=command_headers(csrf, "shadow-finish-fixture"))
    assert finished.status_code == 200, finished.text
    assert finished.json()["advisory"]["model_version"] == model.version
    assert client.get(BASE+f"/protocols/{p['id']}/monitor").status_code == 403
    assert "arms" not in client.get(BASE+f"/protocols/{p['id']}").json()["summary"]
    login(client, "research@test.local")
    report = client.get(BASE+f"/protocols/{p['id']}/monitor").json()
    assert report["shadow_completed"] == 1 and report["automatic_retraining"] is False
    assert all(s["suppressed"] for s in report["age_slices"].values())
    assert db_session.scalar(select(func.count()).select_from(Visit)) == 0
    assert db_session.get(ModelVersion, model.id).active is False


def test_dataset_hash_rejects_changed_file_and_model_mismatch(client, db_session, research_data, tmp_path):
    csrf = login(client, "research@test.local")
    Path(research_data.file_path).write_text("changed bytes")
    r = client.post(BASE+"/protocols", json={"name": "Changed source test", "question": "A changed source must not be silently accepted", "dataset_id": str(research_data.id)}, headers=command_headers(csrf, "changed-source-protocol"))
    assert r.status_code == 422 and "hash" in r.text
    assert client.post(BASE+"/protocols", json={"name": "Missing model test", "question": "A shadow study needs a versioned model", "dataset_id": str(research_data.id), "design": "SHADOW"}, headers=command_headers(csrf, "missing-model-protocol")).status_code == 422


def test_operations_worker_protocol_binding_exports_and_failure(client, db_session, research_data, monkeypatch):
    from app.worker import execute_job, work_once
    from sqlalchemy.orm import sessionmaker
    csrf = login(client, "research@test.local"); p = publish(client, csrf, research_data)
    response = client.post(BASE+f"/protocols/{p['id']}/operations", json={}, headers=command_headers(csrf, "operations-study-worker"))
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    assert client.get(BASE+f"/runs/{run_id}/export").status_code == 409
    assert client.post(BASE+f"/protocols/{p['id']}/operations", json={}, headers=command_headers(csrf, "operations-already-queued")).status_code == 409
    job = db_session.get(Job, uuid.UUID(response.json()["job_id"]))
    execute_job(db_session, job); db_session.commit()
    result = client.get(BASE+f"/runs/{run_id}").json()
    assert result["status"] == "COMPLETED" and result["results"]["protocol_hash"] == p["config_hash"]
    assert "wait_prediction" in result["results"] and "resource_planning" in result["results"]
    assert client.get(BASE+f"/runs/{run_id}/export?format=csv").status_code == 200
    # A later job cannot use a different configuration under the same frozen hash.
    follow = client.post(BASE+f"/protocols/{p['id']}/operations", json={}, headers=command_headers(csrf, "operations-failure-fixture")).json()
    pending = db_session.get(Job, uuid.UUID(follow["job_id"]))
    pending.config_json = {**pending.config_json, "protocol_hash": "invalid"}; db_session.commit()
    work_once(sessionmaker(bind=db_session.get_bind(), expire_on_commit=False))
    db_session.expire_all()
    failed = client.get(BASE+f"/runs/{follow['run_id']}").json()
    assert failed["status"] == "FAILED" and "protocol" in failed["error"]
    login(client, "other@test.local")
    assert client.get(BASE+f"/runs/{run_id}").status_code == 404


def test_counterbalanced_arms_distinct_and_explanations_only_in_assigned_arm(client, db_session, research_data, tmp_path):
    model = create_model(db_session, research_data, tmp_path)
    csrf = login(client, "research@test.local")
    p = publish(client, csrf, research_data, design="COUNTERBALANCED", model_id=str(model.id))
    csrf = login(client, "clinician@test.local"); arms = []
    for i in range(3):
        r = client.post(BASE+f"/protocols/{p['id']}/trials/start", json={"consented": True, "consent_ref": "COUNTERBALANCED_FIXTURE"}, headers=command_headers(csrf, f"counterbalance-start-{i}"))
        assert r.status_code == 201, r.text
        t = r.json(); arms.append(t["arm"])
        if t["arm"] == "MANUAL": assert t["advisory"] is None
        elif t["arm"] == "ADVISORY": assert "contrastive" not in t["advisory"] and "factors" not in t["advisory"]
        else: assert "factors" in t["advisory"]
        assert client.post(BASE+f"/trials/{t['id']}/complete", json={"label": "P3", "reason": "Synthetic test response", "understands_authority": True, "trust_rating": 3}, headers=command_headers(csrf, f"counterbalance-finish-{i}")).status_code == 200
    assert set(arms) == {"MANUAL", "ADVISORY", "EXPLANATION"}
