"""Retain a repeatable synthetic ML/operations demonstration through the real API.

No model review/activation, patient command, roster change or participant response
is fabricated here. Human-study workflows are verified separately in a disposable
browser-test environment, and are never counted as actual recruitment.
"""
import argparse
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", default="docs/evidence")
    args = parser.parse_args()
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    csrf = None

    def request(path, body=None, raw=False):
        headers = {"Accept": "application/json"}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})
            if csrf:
                headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(args.base_url + "/api/v1" + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with opener.open(req, timeout=30) as response:
            payload = response.read()
            return payload if raw else json.loads(payload)

    def wait(job_id):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            job = request("/research/jobs/" + job_id)
            if job["status"] == "COMPLETED":
                return job
            if job["status"] == "FAILED":
                raise RuntimeError(job["error"])
            time.sleep(.5)
        raise RuntimeError("Research worker has not completed; inspect durable jobs")

    csrf = request("/auth/login", {"email": "research@demo.hutano.test", "password": "DemoResearch1!"})["csrf_token"]
    job = request("/research/models/train", {"seed": 2026})
    trained = wait(job["job_id"])
    overview = request("/research/workbench/overview")
    model = next(m for m in overview["models"] if m["id"] == trained["result_ref"])
    reliability = model["metrics"]["reliability_research"]
    assert set(reliability["partitions"]) == {"fit", "model_selection", "calibration", "threshold_selection", "final_test"}
    protocol = request("/research/workbench/protocols", {
        "name": "Verified research-depth operations · synthetic",
        "question": "On independent synthetic days, do evaluated waiting intervals and learned forecast planning improve on simpler operational comparators under equal paid staff hours?",
        "dataset_id": model["dataset_id"], "design": "MANUAL_ONLY", "case_count": 24,
        "operations_config": {"seed": 2026, "training_days": 40, "test_days": 12, "arrivals_per_day": 50,
                              "replications": 10, "shift_strength": 1., "missing_rate": 0.}})
    results = []; run_ids = []
    for _ in range(2):
        queued = request(f"/research/workbench/protocols/{protocol['id']}/operations", {})
        wait(queued["job_id"])
        run = request("/research/workbench/runs/" + queued["run_id"])
        assert run["status"] == "COMPLETED"
        results.append(run["results"]); run_ids.append(run["id"])
    assert results[0] == results[1], "All metrics, traces, configurations and hashes must reproduce"
    result = results[0]
    assert result["priority_effect"] == "NONE" and result["live_schedule_mutations"] is False
    for scenario in result["resource_planning"]["sensitivities"]:
        assert len(scenario["policies"]) == 4
        assert all(p["paid_staff_minutes"] == 1080 and p["all_constraints_valid"] for p in scenario["policies"].values())
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    for fmt in ["json", "csv"]:
        (output/f"operations-research.{fmt}").write_bytes(request(f"/research/workbench/runs/{run_ids[0]}/export?format={fmt}", raw=True))
    (output/"advisory-reliability.json").write_text(json.dumps(model, indent=2, allow_nan=False) + "\n")
    (output/"research-protocol.json").write_bytes(request(f"/research/workbench/protocols/{protocol['id']}/export", raw=True))
    base = result["resource_planning"]["sensitivities"][0]
    evidence = {"verified_at": datetime.now(timezone.utc).isoformat(), "status": "PASS",
                "protocol_id": protocol["id"], "protocol_hash": protocol["config_hash"], "run_ids": run_ids,
                "repeated_results_identical": True, "model_version": model["version"], "model_status": model["status"],
                "model_lifecycle_commands": 0, "participant_responses_created": 0, "patient_or_schedule_commands": 0,
                "wait_prediction": result["wait_prediction"]["test"],
                "learned_minus_historical": base["paired_comparisons"]["learned_minus_historical_planning"],
                "raw_log_loss": reliability["raw"]["log_loss"], "calibrated_log_loss": reliability["calibrated"]["log_loss"],
                "selected_threshold_test": reliability["selected_threshold_test"],
                "limitations": ["Synthetic software verification, not clinical effectiveness or human recruitment",
                                "Existing data retained; this command adds protocol/run/model research evidence"]}
    (output/"research-depth-demo.json").write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
