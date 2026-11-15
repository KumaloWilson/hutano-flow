"""Pure operational-research tests; no live data or schedule mutation."""
import json

import numpy as np
import pytest

from app.ml.operations_study import (
    DEFAULTS, FEATURES, HORIZON, POLICIES, _cohort, _partition, _schedules,
    _simulate, _timestamp, _wait_study, normalize_operations_config,
    run_operations_study,
)


SMALL = {"training_days": 28, "test_days": 4, "arrivals_per_day": 20, "replications": 2,
         "missing_rate": .2}


@pytest.fixture(scope="module")
def study():
    return run_operations_study(SMALL)


def test_operations_config_rejects_unbounded_unknown_and_nonfinite_work():
    assert normalize_operations_config({}) == DEFAULTS
    for config in [{"other": 2}, {"replications": 1}, {"replications": 41},
                   {"seed": True}, {"training_days": 28.5}, {"missing_rate": float("nan")},
                   {"shift_strength": float("inf")}, {"arrivals_per_day": "50"}]:
        with pytest.raises(ValueError):
            normalize_operations_config(config)


def test_operations_study_is_reproducible_json_safe_and_nonclinical(study):
    again = run_operations_study(SMALL)
    assert study == again
    json.dumps(study, allow_nan=False)
    assert study["priority_effect"] == "NONE"
    assert study["live_schedule_mutations"] is False
    assert study["provenance"]["source"] == "SEEDED_SYNTHETIC_ONLY"
    assert "whole-outpatient-journey" in study["definitions"]["scope"]


def test_wait_model_partitions_targets_and_missingness_are_auditable(study):
    result = study["wait_prediction"]
    names = ["training", "selection", "calibration", "test"]
    for first, second in zip(names, names[1:]):
        prior, later = result["partitions"][first], result["partitions"][second]
        assert prior["end_exclusive"] == later["start"]
        assert prior["latest_outcome_available_at"] < later["start"]
    assert 0 <= result["test"]["interval_coverage"] <= 1
    assert result["test"]["mean_interval_width_minutes"] >= 0
    assert result["test"]["mae_minutes"] >= 0
    assert result["test"]["baseline_mae_minutes"] >= 0
    assert any(s["slice"] == "queue_missing" and s["value"] for s in result["slices"])
    for trace in result["prediction_traces"]:
        assert trace["predicted_at"] <= trace["outcome_available_at"]
        assert set(trace["features"]) == set(FEATURES)
        assert trace["interval"][0] <= trace["predicted_wait_minutes"] <= trace["interval"][1]
        if trace["features"]["queue_observation_missing"]:
            assert trace["features"]["queued_ahead"] is None
    assert result["all_arrival_outcomes"]["unserved"] >= result["all_arrival_outcomes"]["not_started"]


def test_final_test_days_cannot_change_model_selection_or_interval_calibration():
    history = np.array([8., 10., 12., 15., 20.])
    base = normalize_operations_config(SMALL)
    first = _wait_study(base, history)
    second = _wait_study({**base, "test_days": 6}, history)
    assert first["selected_estimator"] == second["selected_estimator"]
    assert first["selection_mae_minutes"] == second["selection_mae_minutes"]
    assert first["calibration_margin_minutes"] == second["calibration_margin_minutes"]
    assert first["prediction_traces"] == second["prediction_traces"][:len(first["prediction_traces"])]


def test_outcome_availability_purge_excludes_future_labels():
    rows = [{"started": 5., "outcome_available_at": _timestamp(3, 5)},
            {"started": 0., "outcome_available_at": _timestamp(4, 0)},
            {"started": None}]
    assert _partition(rows, 4) == rows[:1]


def test_prediction_snapshot_cannot_peek_at_in_service_future_end():
    cohort = [{"patient_no": 1, "arrival": 0., "duration": 12., "urgency": 3},
              {"patient_no": 2, "arrival": 1., "duration": 10., "urgency": 3}]
    other = [{**p, "duration": 25.} if p["patient_no"] == 1 else p for p in cohort]
    history = np.array([8., 12., 18.])
    first = _simulate(cohort, _schedules()[0], history=history)
    second = _simulate(other, _schedules()[0], history=history)
    assert first["rows"][1]["features"] == second["rows"][1]["features"]
    assert first["rows"][1]["baseline"] == second["rows"][1]["baseline"]
    assert first["rows"][1]["features"][2] == pytest.approx(np.mean(history - 1))


def test_clinician_category_anchor_dominates_individual_duration():
    cohort = [{"patient_no": i + 1, "arrival": float(i / 10), "duration": 30., "urgency": 3} for i in range(3)]
    cohort += [{"patient_no": 4, "arrival": 1., "duration": 1., "urgency": 5},
               {"patient_no": 5, "arrival": 2., "duration": 29., "urgency": 1}]
    result = _simulate(cohort, _schedules()[0])
    starts = [event["patient_no"] for event in result["trace"] if event["event"] == "STARTED"]
    assert starts.index(5) < starts.index(4)
    assert result["rows"][4]["urgency"] == 1
    assert result["rows"][3]["urgency"] == 5


def test_empty_and_all_unserved_days_do_not_invent_zero_completed_wait():
    empty = _simulate([], _schedules()[0])
    assert empty["metrics"]["arrivals"] == 0
    assert empty["metrics"]["mean_wait_minutes"] is None
    cohort = [{"patient_no": 1, "arrival": 470., "duration": 1., "urgency": 1}]
    result = _simulate(cohort, _schedules()[0])
    assert result["metrics"]["unserved"] == 1
    assert result["metrics"]["mean_wait_minutes"] is None
    assert result["metrics"]["all_arrival_accumulated_wait_mean_minutes"] == HORIZON - 470


def test_completion_exactly_at_closing_is_counted_without_overtime():
    cohort = [{"patient_no": 1, "arrival": 450., "duration": 30., "urgency": 3}]
    result = _simulate(cohort, _schedules()[2])
    assert result["rows"][0]["ended"] == HORIZON
    assert result["metrics"]["completed"] == 1
    assert result["metrics"]["unserved"] == 0
    assert result["metrics"]["budget_and_window_constraints_valid"]


def test_all_planning_comparators_preserve_budget_and_report_losses_without_filtering(study):
    planning = study["resource_planning"]
    assert len(planning["allowed_schedules"]) == 6
    for schedule in planning["allowed_schedules"]:
        assert sum(room["shift"][1] - room["shift"][0] for room in schedule["rooms"]) == 1080
        assert sum(room["break"][1] - room["break"][0] for room in schedule["rooms"]) == 90
    assert {r["scenario"] for r in planning["sensitivities"]} == {"BASE", "LOW_LOAD", "HIGH_LOAD", "ROOM_OUTAGE"}
    for scenario in planning["sensitivities"]:
        assert set(scenario["policies"]) == set(POLICIES)
        assert len(scenario["input_hashes"]) == SMALL["replications"]
        arrivals = []
        for policy, report in scenario["policies"].items():
            assert report["all_constraints_valid"]
            assert report["paid_staff_minutes"] == 1080
            assert report["planned_service_minutes"] == 990
            runs = scenario["replication_metrics"][policy]
            arrivals.append([run["arrivals"] for run in runs])
            assert report["unserved_mean"] >= 0
            assert all(run["occupied_minutes"] <= run["available_service_minutes_after_outage"] for run in runs)
        assert all(arrivals[0] == values for values in arrivals)
        for comparison in scenario["paired_comparisons"].values():
            assert comparison["pairs"] == SMALL["replications"]
            lo, hi = comparison["paired_95_ci"]
            assert lo <= comparison["mean_difference_minutes"] <= hi
    # All candidate scores are retained, not only the selected/favourable ones.
    assert all(len(decision["candidate_scores"]) == 6 for decision in planning["planning_decisions"])
    assert set(planning["replay"]) == set(POLICIES)


def test_heavy_load_outage_remains_within_hard_paid_hours():
    cohort = _cohort(42, np.repeat(40., 8))
    for schedule in _schedules():
        result = _simulate(cohort, schedule, outage=True)
        assert result["metrics"]["budget_and_window_constraints_valid"]
        assert result["metrics"]["unserved"] > 0
        assert result["metrics"]["all_arrival_accumulated_wait_total_minutes"] > 0
