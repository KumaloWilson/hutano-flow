"""The intelligence layer, aligned with the proposal (ADR-033 .. ADR-036)."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.evaluation import cronbach_alpha, sus_score
from app.ml.pipeline import FEATURES, VITAL_FEATURES, generate_synthetic_training_data, train_model
from app.models import Dataset, Job, ModelVersion, QueueEntry, ServiceEpisode, User, utcnow
from app.simulation.engine import run_comparison
from app.worker import execute_job
from conftest import command_headers, login
from test_workflow import create_registered_visit


@pytest.fixture(scope="module")
def v3_model(tmp_path_factory):
    return train_model(generate_synthetic_training_data(2026, 600), tmp_path_factory.mktemp("v3"), 2026)


def activate(db_session, trained):
    dataset = db_session.scalar(select(Dataset))
    clinician = db_session.scalar(select(User).where(User.email == "clinician@test.local"))
    db_session.add(ModelVersion(facility_id=dataset.facility_id, model_name="v3 clinical-feature test", version=trained["version"],
                                artifact_path=trained["artifact_path"], feature_schema_hash=trained["feature_schema_hash"], dataset_id=dataset.id,
                                metrics_json=trained["metrics"], status="REVIEWED", active=True, reviewed_by=clinician.id))
    db_session.commit()


# ------------------------------------------------------------- Objective 2: routine data in


def test_model_schema_uses_triage_vital_signs(v3_model):
    schema = v3_model["metrics"]["feature_schema"]
    assert schema["version"] == "clinical-features-v3" and schema["features"] == FEATURES
    assert set(VITAL_FEATURES) <= set(schema["features"]) and "recorded_measurement" not in schema["features"]
    assert v3_model["metrics"]["macro_f1"] > v3_model["metrics"]["comparators"]["majority"]["macro_f1"]
    assert v3_model["metrics"]["missingness"]["oxygen_saturation"] > 0  # quantified before imputation


def test_advisory_reads_the_visit_record_and_explains_in_plain_language(client, db_session, v3_model):
    activate(db_session, v3_model)
    csrf = login(client, "reception@test.local")
    visit = create_registered_visit(client, csrf, "Synthetic Vitals")
    client.cookies.clear()
    csrf = login(client, "clinician@test.local")
    recorded = client.post(f"/api/v1/visits/{visit['id']}/observations", json={"observations": [
        {"field_code": "temperature", "value": 38.6}, {"field_code": "pulse", "value": 118}, {"field_code": "respiratory_rate", "value": 26},
        {"field_code": "systolic_pressure", "value": 110}, {"field_code": "diastolic_pressure", "value": 70}]},
        headers=command_headers(csrf, str(uuid.uuid4())))
    assert recorded.status_code == 201, recorded.text
    # No manual feature entry: context comes from registration, vitals from the record,
    # and an unsaved oxygen saturation typed in the triage form.
    response = client.post(f"/api/v1/visits/{visit['id']}/recommendation", json={"observations": {"oxygen_saturation": 94}},
                           headers=command_headers(csrf, str(uuid.uuid4())))
    assert response.status_code == 201, response.text
    advisory = response.json()
    sources = {row["feature"]: row["source"] for row in advisory["inputs"]}
    values = {row["feature"]: row["value"] for row in advisory["inputs"]}
    assert sources["age_band"] == "registration" and values["visit_type"] == "new" and sources["hour"] == "arrival time"
    assert sources["pulse"] == "recorded observation" and values["pulse"] == 118
    assert sources["oxygen_saturation"] == "entered at triage (unsaved)"
    assert advisory["model_suggestion_applied_automatically"] is False
    if advisory["abstained"]:
        assert advisory["reasons"] and "plain_language" not in advisory
    else:
        plain = advisory["plain_language"]
        assert plain["headline"].startswith(f"Suggests {advisory['suggestion']} rather than")
        assert 1 <= len(plain["supporting"]) <= 2 and "not a clinical rule" in plain["caveat"]
    # Visit status and priority untouched by the advisory.
    assert client.get(f"/api/v1/visits/{visit['id']}").json()["status"] == "AWAITING_TRIAGE"


def test_impossible_vital_sign_entries_are_rejected(client, db_session, v3_model):
    activate(db_session, v3_model)
    csrf = login(client, "reception@test.local")
    visit = create_registered_visit(client, csrf, "Synthetic Typo")
    client.cookies.clear()
    csrf = login(client, "clinician@test.local")
    typo = client.post(f"/api/v1/visits/{visit['id']}/observations", json={"observations": [{"field_code": "oxygen_saturation", "value": 140}]},
                       headers=command_headers(csrf, str(uuid.uuid4())))
    assert typo.status_code == 422 and "recordable range" in typo.json()["error"]
    advisory = client.post(f"/api/v1/visits/{visit['id']}/recommendation", json={"observations": {"pulse": 900}},
                           headers=command_headers(csrf, str(uuid.uuid4())))
    assert advisory.status_code == 422
    triage = client.post(f"/api/v1/visits/{visit['id']}/triage", json={"configured_urgency": "P3", "observations": {"temperature": 4},
                         "escalation_required": False, "recommendation_decision": "NO_MODEL", "version": visit["version"]},
                         headers=command_headers(csrf, str(uuid.uuid4())))
    assert triage.status_code == 422


# ------------------------------------------------------- Gap 4: the bottom of the queue


def triage(client, csrf, visit, urgency):
    response = client.post(f"/api/v1/visits/{visit['id']}/triage", json={"configured_urgency": urgency, "reason": "Synthetic", "observations": {},
                           "escalation_required": False, "recommendation_decision": "NO_MODEL", "version": visit["version"]},
                           headers=command_headers(csrf, str(uuid.uuid4())))
    assert response.status_code == 201, response.text


def test_long_wait_and_overtaking_prompt_clinician_review_without_reordering(client, db_session):
    reception = login(client, "reception@test.local")
    low = create_registered_visit(client, reception, "Synthetic Low")
    later = [create_registered_visit(client, reception, f"Synthetic Later {i}") for i in range(2)]
    client.cookies.clear()
    clinician = login(client, "clinician@test.local")
    triage(client, clinician, low, "P5")
    for visit in later:
        triage(client, clinician, visit, "P2")
    point = next(ep for ep in client.get(f"/api/v1/visits/{low['id']}").json()["episodes"] if ep["service_type"] == "consultation")["service_point_id"]
    # Make the P5 patient's wait long and the P2 patients "later arrivals" already called.
    low_entry = db_session.scalar(select(QueueEntry).join(QueueEntry.episode).where(ServiceEpisode.visit_id == uuid.UUID(low["id"]), QueueEntry.service_point_id == uuid.UUID(point)))
    low_entry.joined_at = utcnow() - timedelta(minutes=150)
    low_entry.episode.queued_at = low_entry.joined_at
    # As if triage happened 150 minutes ago (the review clock starts at the last assessment).
    from app.models import TriageAssessment
    for assessment in db_session.scalars(select(TriageAssessment).where(TriageAssessment.visit_id == uuid.UUID(low["id"]))):
        assessment.assessed_at = low_entry.joined_at
    db_session.commit()
    entries = client.get(f"/api/v1/service-points/{point}/queue").json()["entries"]
    order_before = [e["visit_id"] for e in entries]
    flagged = next(e for e in entries if e["visit_id"] == low["id"])
    assert flagged["review_recommended"] and flagged["minutes_since_review"] >= 150
    assert flagged["explanations"][0].startswith("Clinician review suggested")
    assert order_before[-1] == low["id"]  # P5 stays behind P2: the prompt never reorders
    assert not next(e for e in entries if e["visit_id"] == later[0]["id"])["review_recommended"]  # recent P2
    # Two later P2 arrivals are called first: both count as overtaking the waiting P5 patient.
    for _ in range(2):
        head = client.get(f"/api/v1/service-points/{point}/queue").json()["entries"][0]
        assert client.post(f"/api/v1/queue/{head['queue_entry_id']}/call", json={"version": head["version"]},
                           headers=command_headers(clinician, str(uuid.uuid4()))).status_code == 200
    remaining = client.get(f"/api/v1/service-points/{point}/queue").json()["entries"]
    assert [e["visit_id"] for e in remaining] == [low["id"]] and remaining[0]["overtaken_by"] == 2
    # A clinician reviews and confirms the category: the review clock restarts.
    detail = client.get(f"/api/v1/visits/{low['id']}").json()
    assert client.post(f"/api/v1/visits/{low['id']}/reassess", json={"version": detail["version"], "configured_urgency": "P5",
                       "reason": "Reviewed after long wait; category unchanged", "action": "REASSESS"},
                       headers=command_headers(clinician, str(uuid.uuid4()))).status_code == 200
    refreshed = next(e for e in client.get(f"/api/v1/service-points/{point}/queue").json()["entries"] if e["visit_id"] == low["id"])
    assert not refreshed["review_recommended"] and refreshed["minutes_since_review"] < 5


def test_research_arms_quantify_bottom_of_queue_tradeoffs_without_changing_base_results():
    params = dict(seed=11, patient_count=90, replications=4, servers=2, arrival_rate_per_hour=14, mean_service_minutes=12)
    base = run_comparison(**params)
    research = run_comparison(**params, include_research_arms=True)
    assert set(base["policies"]) == {"FCFS", "URGENCY_FIRST", "HYBRID"}
    assert set(research["policies"]) == {"FCFS", "URGENCY_FIRST", "HYBRID", "AGEING_BOUNDED", "DURATION_AWARE"}
    for policy in base["policies"]:
        assert base["policies"][policy]["waiting_minutes"] == research["policies"][policy]["waiting_minutes"]
    assert base["input_sequence_hashes"] == research["input_sequence_hashes"]
    fairness = research["policies"]["URGENCY_FIRST"]["fairness"]
    assert fairness["overtaken_by_urgency"]["P5"]["maximum"] >= research["policies"]["FCFS"]["fairness"]["overtaken_by_urgency"]["P5"]["maximum"]
    assert research["policies"]["AGEING_BOUNDED"]["research_only"] and "RESEARCH ONLY" in research["research_arms"]["AGEING_BOUNDED"]
    tests = research["inferential"]["paired_vs_fcfs_mean_journey_wait"]
    assert set(tests) == {"URGENCY_FIRST", "HYBRID", "AGEING_BOUNDED", "DURATION_AWARE"} and tests["HYBRID"]["n"] == 4


# ------------------------------------------------- Objective 1 + simulation calibration


def test_baseline_import_measures_and_calibrated_simulation_reproduces_it(client, db_session):
    csrf = login(client, "research@test.local")
    example = client.get("/api/v1/research/baseline/synthetic-example?days=8")
    assert example.status_code == 200 and example.text.startswith("journey_no,stage")
    imported = client.post("/api/v1/research/baseline/import", data={"name": "Synthetic baseline", "provenance": "Generated synthetic time-motion example",
                           "preview_only": "false"}, files={"file": ("baseline.csv", example.content, "text/csv")},
                           headers=command_headers(csrf, str(uuid.uuid4())))
    assert imported.status_code == 201, imported.text
    report = imported.json()
    assert report["arrivals_by_hour"] and report["queue_length_by_hour"]["registration"]
    assert report["morning_arrival_share"] > .7 and report["bottleneck_stage"]
    assert report["littles_law"]["stages"]["registration"]["assessable"] and report["littles_law"]["stages"]["registration"]["consistent"]
    assert report["simulation_inputs"]["stage_capacities"]["registration"] == 1
    run = client.post("/api/v1/simulations/calibrated", json={"dataset_id": report["id"], "replications": 10},
                      headers=command_headers(csrf, str(uuid.uuid4())))
    assert run.status_code == 202, run.text
    execute_job(db_session, db_session.get(Job, uuid.UUID(run.json()["job_id"])))
    db_session.commit()
    results = client.get(f"/api/v1/simulations/{run.json()['id']}").json()["results"]
    validation = results["calibration_validation"]
    assert validation["checks"] and validation["reproduces_baseline"], validation
    assert results["calibration"]["baseline_dataset_hash"] == report["dataset_hash"]
    assert "AGEING_BOUNDED" in results["policies"]


# -------------------------------------------- Objective 4: usability and acceptance


def test_sus_scoring_and_alpha():
    assert sus_score([3] * 10) == 50
    assert sus_score([5, 1] * 5) == 100 and sus_score([1, 5] * 5) == 0
    assert cronbach_alpha([[1, 1], [2, 2]]) is None
    assert cronbach_alpha([[1, 2, 1], [3, 3, 4], [5, 5, 5], [2, 2, 2]]) > .9


def test_feedback_records_sus_and_tam_and_evaluation_report_tracks_objectives(client):
    csrf = login(client, "research@test.local")
    bad = client.post("/api/v1/research/feedback", json={"role_group": "nurse", "task_id": "call_next", "consent_ref": "C-01",
                      "response": {"sus": [3] * 9}}, headers=command_headers(csrf, str(uuid.uuid4())))
    assert bad.status_code == 422
    for index, (sus, pu, peou) in enumerate([([4, 2, 4, 2, 4, 2, 4, 2, 4, 2], [6, 6, 5, 6], [5, 6, 6, 6]),
                                             ([5, 1, 5, 1, 4, 2, 5, 1, 5, 2], [7, 6, 7, 7], [6, 7, 7, 6]),
                                             ([3, 3, 3, 3, 3, 3, 3, 3, 3, 3], [4, 4, 5, 4], [4, 4, 4, 5])]):
        ok = client.post("/api/v1/research/feedback", json={"role_group": "nurse", "task_id": "call_next", "consent_ref": f"C-{index}",
                         "response": {"completed": True, "duration_seconds": 40, "errors": 0, "sus": sus,
                                      "tam": {"perceived_usefulness": pu, "perceived_ease_of_use": peou}}},
                         headers=command_headers(csrf, str(uuid.uuid4())))
        assert ok.status_code == 201, ok.text
    summary = client.get("/api/v1/research/feedback/summary").json()["acceptance"]
    assert summary["sus"]["n"] == 3 and summary["sus"]["mean"] == pytest.approx((75 + 92.5 + 50) / 3, abs=.01)
    assert summary["tam"]["perceived_usefulness"]["cronbach_alpha"] is not None
    instruments = client.get("/api/v1/research/instruments").json()
    assert len(instruments["sus"]["items"]) == 10 and len(instruments["tam"]["items"]["perceived_usefulness"]) == 4
    report = client.get("/api/v1/research/evaluation").json()
    assert [o["id"] for o in report["objectives"]] == ["O1", "O2", "O3", "O4"]
    assert "SYNTHETIC" in report["research_label"]
    o4 = report["objectives"][3]
    assert o4["evidence"]["usability_and_acceptance"]["sus"]["n"] == 3
    client.cookies.clear()
    login(client, "reception@test.local")
    assert client.get("/api/v1/research/evaluation").status_code == 403
