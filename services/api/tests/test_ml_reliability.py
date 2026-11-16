"""Research-methodology regression tests, using generated labels only."""
import json
import math

import joblib
import numpy as np
import pandas as pd
import pytest

from app.ml.pipeline import (FEATURES, LABELS, evaluate_shadow, explain_prediction,
    feature_reasons, generate_synthetic_training_data, temporal_partitions,
    train_model, validate_frame)
from app.ml.reliability import (ABSTENTION_COST, bootstrap_intervals, fit_temperature, probability_diagnostics,
    risk_coverage, select_threshold, temperature_probabilities)


@pytest.fixture(scope="module")
def calibrated_model(tmp_path_factory):
    return train_model(generate_synthetic_training_data(8, 300), tmp_path_factory.mktemp("calibrated"), 8)


def test_five_temporal_partitions_and_no_preprocessing_leakage(calibrated_model):
    metrics = calibrated_model["metrics"]
    research = metrics["reliability_research"]
    partitions = research["partitions"]
    assert [p["rows"] for p in partitions.values()] == [150, 30, 30, 30, 60]
    bounds = list(partitions.values())
    assert all(pd.Timestamp(a["end"]) < pd.Timestamp(b["start"]) for a, b in zip(bounds, bounds[1:]))
    assert metrics["estimator_fit_rows"] == 150
    assert metrics["train_rows"] == 240  # Explicitly documented legacy development count.
    artifact = joblib.load(calibrated_model["artifact_path"])
    fit = generate_synthetic_training_data(8, 300).iloc[:150]
    imputer = artifact["pipeline"]["preprocess"].named_transformers_["number"]["impute"]
    from app.ml.pipeline import NUMERIC_FEATURES
    assert imputer.statistics_.tolist() == pytest.approx(fit[NUMERIC_FEATURES].median().tolist())
    assert research["threshold_selection"]["frozen_before_final_test"]
    assert artifact["reference_profile"]["n"] == 150
    metadata = metrics["feature_schema"]["metadata"]
    assert metadata["pulse"]["unit"] == "beats/min" and "missing stays missing" in metadata["pulse"]["definition"]
    assert "not clinical thresholds" in metrics["feature_schema"]["generator_assumptions"]


def test_final_test_labels_cannot_select_estimator_calibrator_or_threshold(calibrated_model, tmp_path):
    frame = generate_synthetic_training_data(8, 300)
    frame.loc[240:, "urgency"] = "P5"
    changed = train_model(frame, tmp_path, 8)
    original = joblib.load(calibrated_model["artifact_path"])
    mutated = joblib.load(changed["artifact_path"])
    np.testing.assert_array_equal(original["pipeline"]["classifier"].coef_, mutated["pipeline"]["classifier"].coef_)
    assert original["calibration"] == mutated["calibration"]
    assert original["threshold"] == mutated["threshold"]
    assert original["schema"] == mutated["schema"]
    assert original["metrics"]["reliability_research"]["learning_curves"] == mutated["metrics"]["reliability_research"]["learning_curves"]
    assert original["metrics"]["confusion_matrix"] != mutated["metrics"]["confusion_matrix"]


def test_temperature_objective_and_scalar_order_preservation():
    logits = np.tile([[5., 1., 0., -1., -2.]], (20, 1))
    actual = np.array(["P1"] * 10 + ["P2"] * 5 + ["P3"] * 5)
    fit = fit_temperature(logits, actual, LABELS)
    assert fit["calibration_log_loss"] <= fit["uncalibrated_calibration_log_loss"]
    raw = temperature_probabilities(logits)
    calibrated = temperature_probabilities(logits, fit["temperature"])
    assert np.array_equal(raw.argmax(axis=1), calibrated.argmax(axis=1))
    assert np.allclose(calibrated.sum(axis=1), 1)
    diagnostics = probability_diagnostics(actual, calibrated, LABELS)
    assert 0 <= diagnostics["multiclass_brier_score"] <= 2
    assert sum(item["n"] for item in diagnostics["bins"]) == 20


def test_threshold_utility_and_guarded_risk_denominators():
    probabilities = np.array([[.8, .05, .05, .05, .05], [.4, .3, .1, .1, .1], [.8, .05, .05, .05, .05]])
    actual = ["P1", "P2", "P1"]
    eligible = [True, True, False]
    result = select_threshold(actual, probabilities, LABELS, eligible)
    assert result["threshold"] == .45
    assert result["selected"]["research_cost"] == pytest.approx(2 * ABSTENTION_COST / 3)
    curve = risk_coverage(actual, probabilities, LABELS, eligible, thresholds=[0, .45, 1])
    assert curve["overall"][0]["coverage"] == pytest.approx(2 / 3)
    assert curve["overall"][1]["risk"] == 0
    assert curve["overall"][2]["risk"] is None  # Abstention is not zero error.
    assert curve["per_reference_class"]["P3"][0]["coverage"] is None
    assert curve["per_reference_class"]["P1"][1]["coverage"] == .5
    uncertainty = bootstrap_intervals(actual, probabilities, LABELS, .45, eligible, seed=8)
    assert uncertainty["intervals95"]["selective_risk"] is None
    assert uncertainty["selective_risk_wilson_interval95"][1] > 0


def test_exact_raw_contrast_and_calibrated_log_probability_ratio(calibrated_model):
    features = {"age_band": "adult", "visit_type": "new", "arrival_mode": "walk_in", "hour": 9, "temperature": 37.0, "pulse": 80, "respiratory_rate": 16, "oxygen_saturation": 97, "systolic_pressure": 120, "diastolic_pressure": 76}
    result = evaluate_shadow(calibrated_model["artifact_path"], features)
    contrast = result["contrastive"]
    reconstructed = (sum(f["logit_difference_contribution"] for f in contrast["factors"])
                     + contrast["other_logit_difference_contributions"] + contrast["intercept_difference"])
    assert reconstructed == pytest.approx(contrast["raw_logit_difference"])
    ratio = math.log(result["probabilities"][contrast["predicted_class"]] / result["probabilities"][contrast["alternative_class"]])
    assert ratio == pytest.approx(contrast["calibrated_log_probability_ratio"])
    assert ratio == pytest.approx(reconstructed / result["calibration_temperature"])
    assert result["requires_clinician_review"] and not result["model_suggestion_applied_automatically"]


def test_unrecorded_vital_is_explicit_not_imputed_silently(calibrated_model):
    """A missing (NaN/None) vital is 'not recorded' within the allowance, never treated as normal."""
    for missing in (float("nan"), None):
        result = explain_prediction(calibrated_model["artifact_path"], {"age_band": "adult", "visit_type": "new", "arrival_mode": "walk_in", "hour": 9, "temperature": 37.0, "pulse": missing, "respiratory_rate": 16, "oxygen_saturation": 97, "systolic_pressure": 120, "diastolic_pressure": 76})
        assert result["confidence"] is not None and "pulse" in result["not_recorded"]
        assert not any("pulse" in reason for reason in result["reasons"])
    three_missing = explain_prediction(calibrated_model["artifact_path"], {"age_band": "adult", "visit_type": "new", "arrival_mode": "walk_in", "hour": 9,
        "temperature": None, "pulse": None, "respiratory_rate": 16, "oxygen_saturation": None, "systolic_pressure": 120, "diastolic_pressure": 76})
    assert three_missing["abstained"] and three_missing["confidence"] is None
    assert any("Too many measurements not recorded (3 of 5" in reason for reason in three_missing["reasons"])
    # Systolic and diastolic come from one reading: a missing cuff counts once.
    no_cuff = explain_prediction(calibrated_model["artifact_path"], {"age_band": "adult", "visit_type": "new", "arrival_mode": "walk_in", "hour": 9,
        "temperature": 37.0, "pulse": 80, "respiratory_rate": None, "oxygen_saturation": 97, "systolic_pressure": None, "diastolic_pressure": None})
    assert not any("Too many" in reason for reason in no_cuff["reasons"])


@pytest.mark.parametrize("value", [float("inf"), -float("inf"), "NaN", "Infinity", True, {}, []])
def test_inference_rejects_malformed_or_nonfinite_measurement(calibrated_model, value):
    result = explain_prediction(calibrated_model["artifact_path"], {
        **{"age_band": "adult", "visit_type": "new", "arrival_mode": "walk_in", "hour": 9, "temperature": 37.0, "pulse": 80, "respiratory_rate": 16, "oxygen_saturation": 97, "systolic_pressure": 120, "diastolic_pressure": 76}, "pulse": value})
    assert result["abstained"] and result["suggestion"] is None and result["confidence"] is None
    assert result["reasons"]
    json.dumps(result, allow_nan=False)


def test_reliability_outputs_finite_and_stresses_do_not_hide_abstention(calibrated_model):
    metrics = calibrated_model["metrics"]
    json.dumps(metrics, allow_nan=False)
    research = metrics["reliability_research"]
    scenarios = {row["scenario"]: row for row in research["stress_tests"]["scenarios"]}
    unchanged = scenarios["unchanged"]
    for name in ("measurement_missing_30_percent", "unseen_category_30_percent", "outside_fit_range_30_percent"):
        assert scenarios[name]["input_guard_flag_rate"] >= unchanged["input_guard_flag_rate"]
        assert scenarios[name]["coverage"] <= unchanged["coverage"]
    assert scenarios["label_shift_30_percent"]["input_guard_flag_rate"] == unchanged["input_guard_flag_rate"]
    assert {"macro_f1", "accuracy", "coverage", "selective_risk", "calibrated_minus_raw_log_loss", "calibrated_minus_raw_brier_score"} <= set(research["heldout_uncertainty"]["intervals95"])
    assert len(research["learning_curves"]) == 4
    assert research["explanation_stability"]["available"]
    assert research["ordinal_comparator"]["probability_metrics"]["log_loss"] >= 0


def test_legacy_artifact_remains_usable(calibrated_model, tmp_path):
    artifact = joblib.load(calibrated_model["artifact_path"])
    artifact.pop("calibration")
    artifact.pop("threshold")
    legacy_path = tmp_path / "legacy.joblib"
    joblib.dump(artifact, legacy_path)
    result = explain_prediction(str(legacy_path), {"age_band": "adult", "visit_type": "new", "arrival_mode": "walk_in", "hour": 9, "temperature": 37.0, "pulse": 80, "respiratory_rate": 16, "oxygen_saturation": 97, "systolic_pressure": 120, "diastolic_pressure": 76})
    assert result["abstention_threshold"] == .55
    assert result["calibration_temperature"] == 1
    assert result["confidence"] == result["raw_confidence"]


def test_tied_class_logits_still_explain_a_distinct_alternative(calibrated_model, tmp_path):
    artifact = joblib.load(calibrated_model["artifact_path"])
    classifier = artifact["pipeline"]["classifier"]
    classifier.coef_[:] = 0
    classifier.intercept_[:] = [2, 2, 1, 0, -1]
    path = tmp_path / "tied-logits.joblib"
    joblib.dump(artifact, path)
    result = explain_prediction(str(path), {"age_band": "adult", "visit_type": "new", "arrival_mode": "walk_in", "hour": 9, "temperature": 37.0, "pulse": 80, "respiratory_rate": 16, "oxygen_saturation": 97, "systolic_pressure": 120, "diastolic_pressure": 76})
    assert result["contrastive"]["predicted_class"] == "P1"
    assert result["contrastive"]["alternative_class"] == "P2"
    assert result["contrastive"]["raw_logit_difference"] == 0


def test_equal_timestamps_stay_together_or_reject_insufficient_partitions():
    frame = generate_synthetic_training_data(8, 300)
    frame.loc[148:153, "observed_at"] = frame.loc[148, "observed_at"]
    parts = temporal_partitions(frame)
    assert len(parts["fit"]) == 148
    for earlier, later in zip(list(parts.values()), list(parts.values())[1:]):
        assert pd.Timestamp(earlier.observed_at.iloc[-1]) < pd.Timestamp(later.observed_at.iloc[0])
    frame["observed_at"] = frame.observed_at.iloc[0]
    with pytest.raises(ValueError, match="Five disjoint temporal partitions"):
        temporal_partitions(frame)


def test_dataset_numeric_infinities_and_final_partition_class_diagnostics():
    frame = generate_synthetic_training_data(8, 300)
    frame.loc[0, "pulse"] = np.inf
    with pytest.raises(ValueError, match="Malformed values"):
        validate_frame(frame)
    small = generate_synthetic_training_data(8, 50)
    # Dataset acceptance is separate from sufficient per-partition class coverage.
    assert validate_frame(small)["label_source"] == "SYNTHETIC"
    small.loc[:24, "urgency"] = "P1"
    with pytest.raises(ValueError, match="at least three examples"):
        temporal_partitions(small)


def test_abstention_display_does_not_reveal_withheld_class():
    from app.ml.pipeline import advisory_for_display
    raw = {"abstained": True, "suggestion": None, "confidence": .3, "predicted_label": "P2",
           "probabilities": {"P2": .3}, "factors": [{"feature": "synthetic"}], "contrastive": {"predicted_class": "P2"}}
    shown = advisory_for_display(raw)
    assert shown["factors"] == [] and shown["suggestion"] is None
    assert "predicted_label" not in shown and "contrastive" not in shown and "probabilities" not in shown
    assert raw["predicted_label"] == "P2"  # Private evaluation evidence was not mutated.


def test_monitoring_challenge_keeps_false_alarms_misses_and_delayed_labels(calibrated_model):
    challenge = calibrated_model["metrics"]["reliability_research"]["monitoring_challenge"]
    assert challenge["automatic_actions"] is False and challenge["label_delay_windows"] == 1
    by_name = {s["scenario"]: s for s in challenge["scenarios"]}
    assert by_name["UNCHANGED"]["input_detections"] is None
    assert by_name["MISSING_INPUT_SHIFT"]["input_detections"] == 5
    assert by_name["MISSING_INPUT_SHIFT"]["mean_input_delay_windows"] == 0
    for scenario in by_name.values():
        assert 0 <= scenario["input_false_alarm_fraction"] <= 1
        for replication in scenario["replicate_details"]:
            assert all(w["error_available_at_window"] == w["window"]+1 for w in replication["windows"])
