from app.simulation.engine import run_comparison
from conftest import command_headers, login


def test_simulation_is_deterministic_and_honest():
    parameters = dict(seed=2026, patient_count=80, replications=3, servers=2, arrival_rate_per_hour=24, mean_service_minutes=12)
    first = run_comparison(**parameters)
    second = run_comparison(**parameters)
    assert first == second
    assert set(first["policies"]) == {"FCFS", "URGENCY_FIRST", "HYBRID"}
    assert "hybrid_improved_mean_wait" in first["comparison"]
    assert first["research_label"].startswith("SYNTHETIC")


def test_capacity_zero_reports_unserved():
    result = run_comparison(seed=7, patient_count=20, replications=1, servers=0, arrival_rate_per_hour=10, mean_service_minutes=8)
    assert result["policies"]["FCFS"]["completed_mean"] == 0
    assert result["policies"]["FCFS"]["unserved_mean"] == 20
    assert result["policies"]["FCFS"]["waiting_minutes"]["mean"] is None


def test_simulation_api_and_export(client, db_session):
    csrf = login(client, "research@test.local")
    response = client.post("/api/v1/simulations", json={"name": "Acceptance simulation", "seed": 99, "patient_count": 30, "replications": 2, "consultation_servers": 2, "arrival_rate_per_hour": 12, "mean_service_minutes": 10, "high_load": False}, headers=command_headers(csrf, "simulation-acceptance"))
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert client.get(f"/api/v1/simulations/{run_id}/export?format=csv").status_code == 409
    from app.models import Job
    from app.worker import execute_job
    import uuid
    job = db_session.get(Job, uuid.UUID(response.json()["job_id"]))
    execute_job(db_session, job)
    db_session.commit()
    export = client.get(f"/api/v1/simulations/{run_id}/export?format=csv")
    assert export.status_code == 200
    assert "mean_wait_minutes" in export.text


def test_model_unavailable_does_not_block_manual_flow(client):
    csrf = login(client, "clinician@test.local")
    response = client.get("/api/v1/recommendations/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404

