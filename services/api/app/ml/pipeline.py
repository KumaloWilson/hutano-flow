"""Locally trained, inspectable research pipeline. Shipped labels are synthetic."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.dummy import DummyClassifier
from sklearn.metrics import classification_report, confusion_matrix, log_loss, mean_absolute_error
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from app.ml.reliability import (RELIABILITY_VERSION, bootstrap_intervals, fit_temperature,
    probability_diagnostics, risk_coverage, select_threshold, selective_summary,
    temperature_probabilities, wilson_interval)

# Feature schema v3 (ADR-033): visit context plus the six vital signs recorded at triage.
CONTEXT_FEATURES = ["age_band", "visit_type", "arrival_mode", "hour"]
VITAL_FEATURES = ["temperature", "pulse", "respiratory_rate", "oxygen_saturation", "systolic_pressure", "diastolic_pressure"]
FEATURES = CONTEXT_FEATURES + VITAL_FEATURES
NUMERIC_FEATURES = ["hour"] + VITAL_FEATURES
LEGACY_FEATURES = ["age_band", "visit_type", "arrival_mode", "hour", "recorded_measurement"]
SCHEMA_VERSION = "clinical-features-v3"
# Data-entry plausibility for recorded values. These reject impossible entries; they are
# NOT clinical normal ranges, triage cut-offs or alert thresholds (ADR-002).
RECORDING_RANGES = {"hour": (0, 23), "temperature": (30, 45), "pulse": (20, 250), "respiratory_rate": (4, 80),
                    "oxygen_saturation": (50, 100), "systolic_pressure": (50, 260), "diastolic_pressure": (20, 160)}
# Up to this many *measurements* may be unrecorded (systolic and diastolic come from one
# blood-pressure reading). They are modelled through explicit missingness indicators and
# shown to the clinician as "not recorded", never assumed normal.
MAX_MISSING_VITALS = 2
MEASUREMENTS = {"temperature": ["temperature"], "pulse": ["pulse"], "respiratory_rate": ["respiratory_rate"],
                "oxygen_saturation": ["oxygen_saturation"], "blood_pressure": ["systolic_pressure", "diastolic_pressure"]}
HUMAN_NAMES = {"age_band": "Age band", "visit_type": "Visit type", "arrival_mode": "Arrival", "hour": "Arrival hour",
               "temperature": "Temperature", "pulse": "Pulse", "respiratory_rate": "Respiratory rate",
               "oxygen_saturation": "Oxygen saturation", "systolic_pressure": "Systolic pressure",
               "diastolic_pressure": "Diastolic pressure", "recorded_measurement": "Legacy synthetic measurement"}
UNITS = {"hour": ":00", "temperature": "°C", "pulse": "beats/min", "respiratory_rate": "breaths/min",
         "oxygen_saturation": "%", "systolic_pressure": "mmHg", "diastolic_pressure": "mmHg"}
TARGET = "urgency"
LABELS = ["P1", "P2", "P3", "P4", "P5"]
ORDER = {label: index for index, label in enumerate(LABELS)}
CATEGORIES = {"age_band": ["child", "adult", "older_adult"], "visit_type": ["new", "follow_up", "referral"], "arrival_mode": ["walk_in", "referred"]}
ALLOWED_COLUMNS = set(FEATURES + ["urgency", "service_minutes", "observed_at"])
WARNING = "EXPERIMENTAL — NOT VALIDATED FOR PATIENT CARE; synthetic label agreement only"
PIPELINE_VERSION = "synthetic-logreg-v5-clinical-features"
FEATURE_METADATA = {
    "age_band": {"unit": None, "definition": "Patient age band recorded at registration", "available_at": "registration"},
    "visit_type": {"unit": None, "definition": "New, follow-up or referral visit", "available_at": "registration"},
    "arrival_mode": {"unit": None, "definition": "Walk-in or referred arrival", "available_at": "registration"},
    "hour": {"unit": "hour of day, 0–23", "definition": "Local arrival hour", "available_at": "arrival"},
    **{field: {"unit": UNITS[field], "definition": f"{HUMAN_NAMES[field]} recorded at triage; missing stays missing",
               "available_at": "triage observation", "recording_range": list(RECORDING_RANGES[field])} for field in VITAL_FEATURES},
}
GENERATOR_ASSUMPTIONS = ("Synthetic generator: a latent severity variable shifts vital-sign distributions and labels are "
                         "quantiles of a noisy latent score. These are illustrative generator assumptions, not clinical "
                         "thresholds or validated physiology, and must not be cited as clinical evidence.")


def generate_synthetic_training_data(seed: int = 2026, count: int = 1000) -> pd.DataFrame:
    """Synthetic triage-style rows: context, six vital signs with realistic missingness, label.

    A latent severity variable shifts vital-sign distributions (age-dependent baselines);
    the label is a quantile of a noisy latent score. See GENERATOR_ASSUMPTIONS.
    """
    rng = np.random.default_rng(seed)
    bands = rng.choice(CATEGORIES["age_band"], count, p=[0.2, 0.6, 0.2])
    visit_types = rng.choice(CATEGORIES["visit_type"], count)
    modes = rng.choice(CATEGORIES["arrival_mode"], count, p=[0.85, 0.15])
    severity = rng.normal(0, 1, count)
    child, older = bands == "child", bands == "older_adult"
    temperature = 36.8 + 0.4 * severity + rng.normal(0, 0.35, count)
    pulse = np.where(child, 104, np.where(older, 74, 78)) + 10 * severity + rng.normal(0, 8, count)
    respiratory = np.where(child, 24, np.where(older, 17, 16)) + 2.4 * severity + rng.normal(0, 2, count)
    saturation = 97.6 - 1.3 * np.clip(severity, 0, None) + rng.normal(0, 0.9, count)
    systolic = np.where(child, 100, np.where(older, 136, 122)) - 4 * severity + rng.normal(0, 11, count)
    diastolic = 0.6 * systolic + rng.normal(4, 6, count)
    score = severity + (modes == "referred") * 0.6 + older * 0.25 + rng.normal(0, 0.3, count)
    urgency = pd.cut(score, [-np.inf, -1.2, -0.35, 0.35, 1.2, np.inf], labels=list(reversed(LABELS)))
    def bounded(values, field, decimals):
        low, high = RECORDING_RANGES[field]
        return np.round(np.clip(values, low, high), decimals)
    frame = pd.DataFrame({"age_band": bands, "visit_type": visit_types, "arrival_mode": modes,
        "hour": rng.integers(6, 18, count),
        "temperature": bounded(temperature, "temperature", 1), "pulse": bounded(pulse, "pulse", 0),
        "respiratory_rate": bounded(respiratory, "respiratory_rate", 0), "oxygen_saturation": bounded(saturation, "oxygen_saturation", 0),
        "systolic_pressure": bounded(systolic, "systolic_pressure", 0), "diastolic_pressure": bounded(diastolic, "diastolic_pressure", 0),
        "urgency": urgency.astype(str),
        "service_minutes": np.round(np.clip(10 + (visit_types == "new") * 4 + 1.5 * np.clip(severity, 0, None) + rng.normal(0, 3, count), 1, 40), 3),
        "observed_at": pd.date_range("2026-01-01", periods=count, freq="15min", tz="UTC").astype(str)})
    # Missing completely at random, at rates resembling equipment availability in small clinics.
    for field, rate in {"temperature": .04, "pulse": .04, "respiratory_rate": .18, "oxygen_saturation": .22,
                        "systolic_pressure": .12, "diastolic_pressure": .12}.items():
        frame.loc[rng.random(count) < rate, field] = np.nan
    diastolic_missing = frame.systolic_pressure.isna()
    frame.loc[diastolic_missing, "diastolic_pressure"] = np.nan
    return frame


def validate_frame(frame: pd.DataFrame) -> dict:
    if "recorded_measurement" in frame.columns:
        raise ValueError("Legacy v2 dataset ('recorded_measurement'): use the v3 clinical schema with the six recorded vital signs")
    unknown = set(frame.columns) - ALLOWED_COLUMNS
    if unknown:
        raise ValueError("Unexpected columns rejected: " + ", ".join(sorted(unknown)))
    required = set(FEATURES + [TARGET, "service_minutes", "observed_at"])
    if required - set(frame.columns):
        raise ValueError("Missing schema columns: " + ", ".join(sorted(required - set(frame.columns))))
    if not 50 <= len(frame) <= 20000:
        raise ValueError("Use 50–20,000 de-identified synthetic rows")
    for column, options in {**CATEGORIES, "urgency": LABELS}.items():
        if not frame[column].dropna().isin(options).all():
            raise ValueError(f"Invalid category in {column}")
    if frame[TARGET].isna().any():
        raise ValueError("Target labels cannot be missing")
    for column, (lower, upper) in [*RECORDING_RANGES.items(), ("service_minutes", (0.01, 1440))]:
        values = pd.to_numeric(frame[column], errors="raise")
        if values.notna().sum() == 0:
            raise ValueError(f"Training requires observed values for {column}")
        if not values.dropna().between(lower, upper).all() or (column == "service_minutes" and values.isna().any()):
            raise ValueError(f"Malformed values in {column}")
        frame[column] = values
    dates = pd.to_datetime(frame["observed_at"], utc=True, errors="raise")
    if dates.isna().any():
        raise ValueError("Missing source timestamps")
    if frame.duplicated().any():
        raise ValueError("Duplicate rows rejected to reduce leakage risk")
    return {"columns": list(frame.columns), "missing": {k: int(v) for k, v in frame.isna().sum().items()},
            "missing_fraction": {k: round(float(v), 4) for k, v in frame.isna().mean().items()},
            "missing_vitals_per_row": {str(k): int(v) for k, v in frame[VITAL_FEATURES].isna().sum(axis=1).value_counts().sort_index().items()},
            "class_distribution": {str(k): int(v) for k, v in frame[TARGET].value_counts().items()},
            "label_source": "SYNTHETIC", "warnings": ["No subject identifiers: repeated-subject leakage cannot be ruled out for external data."]}


def preprocessing() -> ColumnTransformer:
    return ColumnTransformer([
        ("category", Pipeline([("impute", SimpleImputer(strategy="constant", fill_value="MISSING")),
            ("encode", OneHotEncoder(handle_unknown="ignore"))]), list(CATEGORIES)),
        ("number", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("scale", StandardScaler())]), NUMERIC_FEATURES),
    ])


def classification_metrics(actual, predicted) -> dict:
    report = classification_report(actual, predicted, labels=LABELS, output_dict=True, zero_division=0)
    return {"macro_f1": float(report["macro avg"]["f1-score"]),
        "per_class": {label: report[label] for label in LABELS},
        "confusion_matrix": confusion_matrix(actual, predicted, labels=LABELS).tolist(), "labels": LABELS,
        "under_triage_against_synthetic_label_count": int(sum(ORDER[p] > ORDER[a] for a, p in zip(actual, predicted))),
        "over_triage_against_synthetic_label_count": int(sum(ORDER[p] < ORDER[a] for a, p in zip(actual, predicted)))}


def temporal_partitions(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Do not split equal source timestamps across stages of model development."""
    dates = pd.to_datetime(frame.observed_at, utc=True)
    boundaries = [0]
    for proportion in (0.5, 0.6, 0.7, 0.8):
        nominal = int(len(frame) * proportion)
        boundaries.append(int(dates.searchsorted(dates.iloc[nominal], side="left")))
    boundaries.append(len(frame))
    names = ["fit", "model_selection", "calibration", "threshold_selection", "final_test"]
    parts = {name: frame.iloc[start:stop] for name, start, stop in zip(names, boundaries, boundaries[1:])}
    if any(len(part) < 5 for part in parts.values()):
        raise ValueError("Five disjoint temporal partitions each need at least five rows; equal timestamps stay together. Supply more distinct synthetic observations.")
    fit = parts["fit"]
    if set(fit.urgency) != set(LABELS) or fit.urgency.value_counts().min() < 3:
        raise ValueError("Training fit partition needs at least three examples of every urgency category")
    if any(fit[column].notna().sum() < 3 for column in NUMERIC_FEATURES):
        raise ValueError("Training fit partition needs at least three observed values for each numeric feature")
    return parts


def schema_features(schema: dict) -> list[str]:
    return list(schema.get("features") or LEGACY_FEATURES)


def feature_reasons(schema: dict, features: dict) -> list[str]:
    """Guard inference before imputation; training imputation is not a normality claim.

    Context fields are always required. Up to `max_missing_vitals` vital signs may be
    unrecorded (modelled via missingness indicators and shown as "not recorded").
    """
    reasons, missing_vitals = [], []
    vitals = set(schema.get("vital_features", []))
    categories = schema.get("categories", CATEGORIES)
    for field in schema_features(schema):
        value = features.get(field)
        if value is None or (isinstance(value, (float, np.floating)) and np.isnan(value)):
            if field in vitals:
                missing_vitals.append(field)
            else:
                reasons.append(f"Missing {field}")
        elif field in CATEGORIES:
            if not isinstance(value, str) or value not in categories[field]:
                reasons.append(f"Unseen category: {field}")
        else:
            try:
                numeric = float(value)
                if isinstance(value, (bool, np.bool_)) or not np.isfinite(numeric):
                    reasons.append(f"Invalid non-finite or boolean numeric field: {field}")
                else:
                    lower, upper = schema["numeric_bounds"][field]
                    if not lower <= numeric <= upper:
                        reasons.append(f"Outside training range: {field}")
            except (ValueError, TypeError, OverflowError):
                reasons.append(f"Invalid numeric field: {field}")
    allowed = int(schema.get("max_missing_vitals", 0))
    groups = schema.get("measurements") or {field: [field] for field in vitals}
    missing_groups = [name for name, members in groups.items() if any(member in missing_vitals for member in members)]
    if len(missing_groups) > allowed:
        reasons.append(f"Too many measurements not recorded ({len(missing_groups)} of {len(groups)}; at most {allowed}): "
                       + ", ".join(name.replace("_", " ") for name in missing_groups))
    return reasons


def eligibility(schema: dict, frame: pd.DataFrame) -> np.ndarray:
    return np.array([not feature_reasons(schema, row) for row in frame[schema_features(schema)].to_dict("records")], dtype=bool)


def reference_profile(frame: pd.DataFrame) -> dict:
    return {"population": "Estimator-fit synthetic rows only", "n": len(frame),
            "missingness": {field: float(frame[field].isna().mean()) for field in FEATURES},
            "categorical_frequencies": {field: {str(k): float(v) for k, v in frame[field].value_counts(normalize=True).items()} for field in CATEGORIES},
            "numeric_quantiles": {field: {str(q): float(frame[field].quantile(q)) for q in (0, .1, .25, .5, .75, .9, 1)}
                                  for field in NUMERIC_FEATURES},
            "numeric_mean_std": {field: {"mean": float(frame[field].mean()), "std": float(frame[field].std(ddof=0))}
                                 for field in NUMERIC_FEATURES}}


def classifier_pipeline(seed: int, c: float = 1.0) -> Pipeline:
    return Pipeline([("preprocess", preprocessing()), ("classifier", LogisticRegression(C=c, max_iter=1000, random_state=seed))])


def learning_curves(train: pd.DataFrame, selection: pd.DataFrame, seed: int, c: float) -> list[dict]:
    result = []
    for fraction in (.25, .5, .75, 1.0):
        prefix = train.iloc[:max(1, int(len(train) * fraction))]
        item = {"fit_rows": len(prefix), "evaluation_rows": len(selection), "evaluation_partition": "model_selection, not final test"}
        if set(prefix.urgency) != set(LABELS) or prefix.urgency.value_counts().min() < 3:
            item.update({"available": False, "reason": "Prefix lacks three examples of each neutral category"})
        else:
            estimator = classifier_pipeline(seed, c).fit(prefix[FEATURES], prefix[TARGET])
            predictions = estimator.predict(selection[FEATURES])
            correct = int((predictions == selection[TARGET]).sum())
            item.update({"available": True, "macro_f1": classification_metrics(selection[TARGET], predictions)["macro_f1"],
                         "accuracy": correct / len(selection), "accuracy_ci95": wilson_interval(correct, len(selection)),
                         "uncertainty_note": "Wilson row interval conditional on fitted prefix; no model-selection uncertainty"})
        result.append(item)
    return result


def ordinal_comparison(train: pd.DataFrame, test: pd.DataFrame, seed: int) -> dict:
    """Four cumulative binary logits; enforce monotone tails before differencing."""
    encoded = train[TARGET].map(ORDER).to_numpy()
    tails = []
    for boundary in range(len(LABELS) - 1):
        estimator = classifier_pipeline(seed)
        estimator.fit(train[FEATURES], encoded > boundary)
        tails.append(estimator.predict_proba(test[FEATURES])[:, 1])
    tails = np.minimum.accumulate(np.column_stack(tails), axis=1)
    probabilities = np.column_stack([1 - tails[:, 0], tails[:, :-1] - tails[:, 1:], tails[:, -1]])
    predicted = np.asarray(LABELS)[probabilities.argmax(axis=1)]
    return {**classification_metrics(test[TARGET], predicted),
            "method": "Four fixed-C cumulative binary logistic regressions; running-min monotone-tail correction",
            "probability_metrics": probability_diagnostics(test[TARGET], probabilities, LABELS),
            "role": "Research comparator only; not selected for advisory use",
            "limitation": "Uses ordering only, not equal clinical distances; independent boundary fits are not a proportional-odds model"}


def stress_evaluation(pipeline, test: pd.DataFrame, schema: dict, temperature: float, threshold: float, seed: int) -> dict:
    """Controlled input corruptions retain labels; prior and concept shifts are explicit."""
    rng = np.random.default_rng(seed + 391)
    variants = {"unchanged": test.copy()}
    selected = rng.choice(len(test), max(1, int(len(test) * .3)), replace=False)
    missing = test.copy(); missing.loc[missing.index[selected], ["temperature", "pulse", "respiratory_rate"]] = np.nan
    variants["measurement_missing_30_percent"] = missing
    unseen = test.copy(); unseen.loc[unseen.index[selected], "visit_type"] = "unseen_synthetic_type"
    variants["unseen_category_30_percent"] = unseen
    outside = test.copy(); outside.loc[outside.index[selected], "pulse"] = schema["numeric_bounds"]["pulse"][1] + 1
    variants["outside_fit_range_30_percent"] = outside
    shifted = test.copy(); shifted["pulse"] += schema["reference_profile"]["numeric_mean_std"]["pulse"]["std"] * .75
    variants["measurement_shift_0_75_fit_std"] = shifted
    weights = np.where(test[TARGET].isin(["P1", "P5"]), 3.0, 1.0)
    variants["extreme_category_prior_reweight"] = test.iloc[rng.choice(len(test), len(test), replace=True, p=weights / weights.sum())].reset_index(drop=True)
    concept = test.copy(); concept.loc[concept.index[selected], TARGET] = concept.iloc[selected][TARGET].map(lambda label: LABELS[(ORDER[label] + 1) % 5]).to_numpy()
    variants["label_shift_30_percent"] = concept
    rows = []
    for name, frame in variants.items():
        probabilities = temperature_probabilities(pipeline.decision_function(frame[FEATURES]), temperature)
        allowed = eligibility(schema, frame)
        predictions = pipeline.classes_[probabilities.argmax(axis=1)]
        summary = selective_summary(frame[TARGET], probabilities, pipeline.classes_, threshold, allowed)
        rows.append({"scenario": name, **summary,
                     "input_guard_flag_rate": float((~allowed).mean()),
                     "full_classifier_error_rate": float((predictions != frame[TARGET]).mean()),
                     "macro_f1": classification_metrics(frame[TARGET], predictions)["macro_f1"],
                     "log_loss": float(log_loss(frame[TARGET], probabilities, labels=pipeline.classes_))})
    return {"seed": seed + 391, "scenarios": rows,
            "interpretation": "Controlled synthetic sensitivity study, not prediction of future performance; changed labels are explicit simulated concept shift",
            "monitoring_limitation": "Input-range flags cannot detect all performance changes, especially label shift; no autonomous retraining or activation"}


def stability_evaluation(pipeline, test: pd.DataFrame, schema: dict, temperature: float, threshold: float) -> dict:
    valid = test.loc[eligibility(schema, test), FEATURES].iloc[:40].copy()
    if valid.empty:
        return {"available": False, "reason": "No complete in-range holdout inputs"}
    base_logits = pipeline.decision_function(valid)
    base_probs = temperature_probabilities(base_logits, temperature)
    base_labels = base_probs.argmax(axis=1)
    comparisons = []
    for field, delta in [("hour", 1.0), ("pulse", .05 * schema["reference_profile"]["numeric_mean_std"]["pulse"]["std"]),
                         ("respiratory_rate", .05 * schema["reference_profile"]["numeric_mean_std"]["respiratory_rate"]["std"])]:
        changed = valid.copy()
        lower, upper = schema["numeric_bounds"][field]
        changed[field] = np.clip(changed[field].astype(float) + delta, lower, upper)
        changed_logits = pipeline.decision_function(changed)
        changed_probs = temperature_probabilities(changed_logits, temperature)
        original_vectors = pipeline["preprocess"].transform(valid)
        changed_vectors = pipeline["preprocess"].transform(changed)
        original_vectors = original_vectors.toarray() if hasattr(original_vectors, "toarray") else original_vectors
        changed_vectors = changed_vectors.toarray() if hasattr(changed_vectors, "toarray") else changed_vectors
        alternate_logits = base_logits.copy()
        alternate_logits[np.arange(len(valid)), base_labels] = -np.inf
        alternate_labels = alternate_logits.argmax(axis=1)
        coefficient_difference = pipeline["classifier"].coef_[base_labels] - pipeline["classifier"].coef_[alternate_labels]
        contribution_change = np.sum(np.abs((changed_vectors - original_vectors) * coefficient_difference), axis=1)
        comparisons.append({"field": field, "positive_delta": float(delta), "clipped_to_fit_range": True,
                            "rows_changed": int((changed[field] != valid[field]).sum()),
                            "predicted_label_agreement": float((changed_probs.argmax(axis=1) == base_labels).mean()),
                            "abstention_decision_agreement": float(((changed_probs.max(axis=1) >= threshold) == (base_probs.max(axis=1) >= threshold)).mean()),
                            "mean_absolute_confidence_change": float(np.abs(changed_probs.max(axis=1) - base_probs.max(axis=1)).mean()),
                            "mean_contrastive_contribution_l1_change": float(contribution_change.mean())})
    return {"available": True, "n": len(valid), "perturbations": comparisons,
            "method": "First 40 eligible chronological holdout rows; original predicted-vs-runner-up pair held fixed for attribution comparison",
            "limitation": "Local input sensitivity, not causal or clinical robustness; labels are not redefined after perturbation"}


def monitoring_challenge(pipeline, development, test, schema, temperature, seed):
    """Predeclared window alarms in a controlled synthetic resampling experiment.

    Thresholds consume development data only. Test labels arrive one window late;
    the experiment records missed detections and false alarms, never retrains.
    """
    dev_probs = temperature_probabilities(pipeline.decision_function(development[FEATURES]), temperature)
    dev_error = float((pipeline.classes_[dev_probs.argmax(axis=1)] != development[TARGET]).mean())
    thresholds = {"input_guard_fraction": min(1., float((~eligibility(schema, development)).mean()) + .20),
                  "full_classifier_error_fraction": min(1., dev_error + .20)}
    window_size, shift_window, total_windows, replications = 20, 3, 8, 5
    reports = []
    for scenario in ["UNCHANGED", "MISSING_INPUT_SHIFT", "LABEL_SHIFT"]:
        false_input = false_error = before_input = before_error = 0
        input_delays, error_delays, replicate_details = [], [], []
        for rep in range(replications):
            windows = []
            for window in range(total_windows):
                rng = np.random.default_rng(np.random.SeedSequence([seed, 615, rep, window]))
                sample = test.iloc[rng.integers(0, len(test), window_size)].copy().reset_index(drop=True)
                if window >= shift_window and scenario != "UNCHANGED":
                    changed = rng.choice(window_size, int(window_size * .6), replace=False)
                    if scenario == "MISSING_INPUT_SHIFT":
                        sample.loc[changed, ["temperature", "pulse", "respiratory_rate"]] = np.nan
                    else:
                        sample.loc[changed, TARGET] = sample.loc[changed, TARGET].map(lambda value: LABELS[(ORDER[value]+1) % len(LABELS)])
                probs = temperature_probabilities(pipeline.decision_function(sample[FEATURES]), temperature)
                guard = float((~eligibility(schema, sample)).mean())
                error = float((pipeline.classes_[probs.argmax(axis=1)] != sample[TARGET]).mean())
                windows.append({"window": window, "guard_fraction": guard,
                                "input_alarm": guard > thresholds["input_guard_fraction"],
                                "full_classifier_error_fraction": error,
                                "delayed_error_alarm": error > thresholds["full_classifier_error_fraction"],
                                "error_available_at_window": window+1})
            unchanged = windows if scenario == "UNCHANGED" else windows[:shift_window]
            false_input += sum(w["input_alarm"] for w in unchanged); before_input += len(unchanged)
            # Only outcomes actually released before the declared shift count as pre-shift alarms.
            released = [w for w in unchanged if w["error_available_at_window"] < (total_windows if scenario == "UNCHANGED" else shift_window)]
            false_error += sum(w["delayed_error_alarm"] for w in released); before_error += len(released)
            input_delay = next((w["window"]-shift_window for w in windows[shift_window:] if w["input_alarm"]), None) if scenario != "UNCHANGED" else None
            error_delay = next((w["error_available_at_window"]-shift_window for w in windows[shift_window:]
                                if w["delayed_error_alarm"] and w["error_available_at_window"] < total_windows), None) if scenario != "UNCHANGED" else None
            input_delays.append(input_delay); error_delays.append(error_delay)
            replicate_details.append({"replication": rep, "input_detection_delay_windows": input_delay,
                                      "delayed_error_detection_delay_windows": error_delay, "windows": windows})
        reports.append({"scenario": scenario, "replications": replications,
                        "unchanged_input_alarm_windows": false_input, "unchanged_input_windows": before_input,
                        "input_false_alarm_fraction": false_input/before_input if before_input else None,
                        "unchanged_delayed_error_alarm_windows": false_error, "unchanged_released_error_windows": before_error,
                        "delayed_error_false_alarm_fraction": false_error/before_error if before_error else None,
                        "input_detections": sum(d is not None for d in input_delays) if scenario != "UNCHANGED" else None,
                        "delayed_error_detections": sum(d is not None for d in error_delays) if scenario != "UNCHANGED" else None,
                        "mean_input_delay_windows": float(np.mean([d for d in input_delays if d is not None])) if any(d is not None for d in input_delays) else None,
                        "mean_delayed_error_delay_windows": float(np.mean([d for d in error_delays if d is not None])) if any(d is not None for d in error_delays) else None,
                        "replicate_details": replicate_details})
    return {"thresholds": thresholds, "threshold_basis": "Model-selection partition fraction + 0.20; predeclared engineering rule, not significance or clinical safety",
            "window_size": window_size, "shift_begins_window": shift_window, "window_count": total_windows,
            "label_delay_windows": 1, "seed": seed, "scenarios": reports,
            "automatic_actions": False,
            "limitations": ["Resampled synthetic final-test inputs; repeated rows and small windows, not independent clinical evidence",
                            "An input shift need not increase error; label shift may leave input alarms silent",
                            "Full-classifier error includes guarded/imputed rows and differs from actual suggestion error",
                            "Null delay means no detected shift within observation, not immediate detection",
                            "Monitoring rules are evaluated offline only; no automatic model or priority change"]}


def train_model(frame: pd.DataFrame, artifact_dir: Path, seed: int = 2026) -> dict:
    frame = frame.copy(deep=True)
    quality = validate_frame(frame)
    frame = frame.assign(_date=pd.to_datetime(frame.observed_at, utc=True)).sort_values("_date", kind="stable").drop(columns="_date").reset_index(drop=True)
    parts = temporal_partitions(frame)
    train, selection, calibration, threshold_data, test = [parts[name] for name in ("fit", "model_selection", "calibration", "threshold_selection", "final_test")]
    candidates = []
    for c in (.1, 1.0, 10.0):
        estimator = classifier_pipeline(seed, c).fit(train[FEATURES], train[TARGET])
        score = classification_metrics(selection[TARGET], estimator.predict(selection[FEATURES]))["macro_f1"]
        candidates.append((score, c, estimator))
    selection_score, best_c, pipeline = max(candidates, key=lambda item: (item[0], -item[1]))
    cv = cross_val_score(classifier_pipeline(seed, best_c), train[FEATURES], train[TARGET],
                         cv=StratifiedKFold(3, shuffle=True, random_state=seed), scoring="f1_macro", n_jobs=1)
    schema = {"version": SCHEMA_VERSION, "features": FEATURES, "vital_features": VITAL_FEATURES,
              "max_missing_vitals": MAX_MISSING_VITALS, "measurements": MEASUREMENTS, "metadata": FEATURE_METADATA, "generator_assumptions": GENERATOR_ASSUMPTIONS,
              "categories": {field: [value for value in options if value in set(train[field].dropna())] for field, options in CATEGORIES.items()},
              "numeric_bounds": {column: [float(train[column].min()), float(train[column].max())] for column in NUMERIC_FEATURES},
              "reference_profile": reference_profile(train),
              "missingness_rule": f"Medians and missingness indicators learned on fit rows only. Context fields are required; up to {MAX_MISSING_VITALS} unrecorded vital signs are modelled explicitly and displayed as not recorded, never assumed normal",
              "excluded_outcomes": ["urgency", "service_minutes"],
              "provenance": "Independent generated synthetic observations; no clinical measurements or patient identities"}
    calibration_fit = fit_temperature(pipeline.decision_function(calibration[FEATURES]), calibration[TARGET], pipeline.classes_)
    temperature = calibration_fit["temperature"]
    threshold_probs = temperature_probabilities(pipeline.decision_function(threshold_data[FEATURES]), temperature)
    threshold_selection = select_threshold(threshold_data[TARGET], threshold_probs, pipeline.classes_, eligibility(schema, threshold_data))
    threshold = threshold_selection["threshold"]
    # Everything used in inference is frozen before final_test is examined.
    logits = pipeline.decision_function(test[FEATURES])
    raw_probabilities = temperature_probabilities(logits)
    probabilities = temperature_probabilities(logits, temperature)
    predicted = pipeline.classes_[probabilities.argmax(axis=1)]
    allowed = eligibility(schema, test)
    raw_diagnostics = probability_diagnostics(test[TARGET], raw_probabilities, pipeline.classes_)
    calibrated_diagnostics = probability_diagnostics(test[TARGET], probabilities, pipeline.classes_)
    metrics = classification_metrics(test[TARGET], predicted)
    comparisons = {}
    for name, estimator in [("majority", DummyClassifier(strategy="most_frequent")),
            ("random_forest", RandomForestClassifier(n_estimators=60, max_depth=5, random_state=seed, n_jobs=1))]:
        comparator = Pipeline([("preprocess", preprocessing()), ("classifier", estimator)])
        comparator.fit(train[FEATURES], train[TARGET])
        comparisons[name] = classification_metrics(test[TARGET], comparator.predict(test[FEATURES]))
    regression = Pipeline([("preprocess", preprocessing()), ("regressor", RandomForestRegressor(n_estimators=60, max_depth=5, random_state=seed, n_jobs=1))])
    regression.fit(train[FEATURES], train.service_minutes)
    dataset_hash = hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()
    runtime = {"scikit_learn": sklearn.__version__, "numpy": np.__version__, "pandas": pd.__version__, "joblib": joblib.__version__}
    implementation_hash = hashlib.sha256(json.dumps({"pipeline": PIPELINE_VERSION, "reliability": RELIABILITY_VERSION, "runtime": runtime}, sort_keys=True).encode()).hexdigest()[:8]
    version = f"synthetic-logreg-{dataset_hash[:12]}-{seed}-{implementation_hash}"
    partition_report = {name: {"rows": len(part), "start": str(part.observed_at.iloc[0]), "end": str(part.observed_at.iloc[-1]),
                              "content_hash": hashlib.sha256(part.to_csv(index=False).encode()).hexdigest(),
                              "class_counts": {str(k): int(v) for k, v in part[TARGET].value_counts().items()}} for name, part in parts.items()}
    reliability = {"schema_version": RELIABILITY_VERSION, "partitions": partition_report,
                   "calibration_fit": calibration_fit, "raw": raw_diagnostics, "calibrated": calibrated_diagnostics,
                   "final_test_calibration_improved_log_loss": calibrated_diagnostics["log_loss"] < raw_diagnostics["log_loss"],
                   "threshold_selection": threshold_selection,
                   "selected_threshold_test": selective_summary(test[TARGET], probabilities, pipeline.classes_, threshold, allowed),
                   "risk_coverage": risk_coverage(test[TARGET], probabilities, pipeline.classes_, allowed),
                   "raw_risk_coverage": risk_coverage(test[TARGET], raw_probabilities, pipeline.classes_, allowed),
                   "heldout_uncertainty": bootstrap_intervals(test[TARGET], probabilities, pipeline.classes_, threshold, allowed, seed,
                                                               reference_probabilities=raw_probabilities),
                   "learning_curves": learning_curves(train, selection, seed, best_c),
                   "ordinal_comparator": ordinal_comparison(train, test, seed),
                   "stress_tests": stress_evaluation(pipeline, test, schema, temperature, threshold, seed),
                   "monitoring_challenge": monitoring_challenge(pipeline, selection, test, schema, temperature, seed),
                   "explanation_stability": stability_evaluation(pipeline, test, schema, temperature, threshold)}
    metrics.update({"label_source": "SYNTHETIC", "warning": WARNING, "seed": seed,
        "pipeline_version": PIPELINE_VERSION, "runtime_versions": runtime, "feature_schema": schema,
        "test_rows": len(test), "train_rows": len(frame) - len(test), "estimator_fit_rows": len(train),
        "train_rows_definition": "Legacy key: all development rows before final holdout; only estimator_fit_rows fit estimator/preprocessor",
        "split_strategy": "temporal 50/10/10/10/20 fit/model-selection/calibration/threshold-selection/final-test; tied timestamps kept together",
        "holdout_start": str(test.observed_at.iloc[0]), "class_distribution": quality["class_distribution"],
        "missingness": quality["missing"], "comparators": comparisons,
        "selection_reason": "Logistic regression chosen for exact additive/contrastive explanations; C selected by model-selection macro F1, ties prefer stronger regularisation; every comparator retained",
        "cross_validation_macro_f1": float(cv.mean()), "cross_validation_definition": "Supporting 3-fold stratified CV inside fit rows only; not final performance or hyperparameter selection",
        "model_selection_macro_f1": selection_score, "best_parameters": {"classifier__C": best_c},
        "model_selection_candidates": [{"C": c, "macro_f1": score} for score, c, _ in candidates],
        "duration": {"median_baseline_mae_minutes": float(mean_absolute_error(test.service_minutes, np.full(len(test), train.service_minutes.median()))),
            "random_forest_mae_minutes": float(mean_absolute_error(test.service_minutes, regression.predict(test[FEATURES])))},
        "calibration": {**calibrated_diagnostics, "method": "Independent temperature-fit calibration, evaluated on untouched chronological final test; no clinical calibration claim"},
        "abstention_threshold": threshold, "low_confidence_requires_review_count": int((probabilities.max(axis=1) < threshold).sum()),
        "guarded_abstention_count": int((~allowed | (probabilities.max(axis=1) < threshold)).sum()),
        "reliability_research": reliability,
        "slices": {str(band): {"n": int((test.age_band == band).sum()),
            "macro_f1": float(classification_metrics(test.loc[test.age_band == band, TARGET], predicted[test.age_band == band])["macro_f1"])}
            for band in CATEGORIES["age_band"] if (test.age_band == band).sum() >= 30},
        "slice_policy": "Synthetic age-band diagnostic; n<30 suppressed. Sex is not collected. No fairness inference.",
        "limitations": quality["warnings"] + ["Synthetic labels are not clinician ground truth", "No clinical effectiveness claim",
            "Temperature calibration may worsen final-test performance; both raw and calibrated outcomes retained",
            "Threshold utility is a research assumption, not a clinical harm function",
            "Unconditional classifier metrics include training-imputed missing inputs; guarded coverage and risk reflect actual advisory eligibility",
            "Observed-at timestamps stand for synthetic prediction time; repeated-subject and retrospective clinical availability are not established"]})
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{version}.joblib"
    joblib.dump({"pipeline": pipeline, "regression": regression, "schema": schema, "metrics": metrics,
                 "calibration": calibration_fit, "threshold": threshold, "reference_profile": schema["reference_profile"]}, path)
    path.chmod(0o600)
    return {"version": version, "artifact_path": str(path), "dataset_hash": dataset_hash,
        "feature_schema_hash": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(), "metrics": metrics}


def train_synthetic_model(artifact_dir: Path, seed: int = 2026) -> dict:
    return train_model(generate_synthetic_training_data(seed), artifact_dir, seed)


def explain_prediction(model_path: str, features: dict) -> dict:
    artifact = joblib.load(model_path)  # only private server-created registry paths reach here
    reasons = feature_reasons(artifact["schema"], features)
    threshold = float(artifact.get("threshold", .55))
    temperature = float(artifact.get("calibration", {}).get("temperature", 1.0))
    if reasons:
        return {"suggestion": None, "confidence": None, "abstained": True, "requires_clinician_review": True,
                "predicted_label": None, "probabilities": None, "factors": [], "reasons": reasons, "warning": WARNING,
                "abstention_threshold": threshold, "calibration_temperature": temperature,
                "model_suggestion_applied_automatically": False}
    pipeline = artifact["pipeline"]
    schema = artifact["schema"]
    fields = schema_features(schema)
    row = pd.DataFrame([{key: features.get(key) for key in fields}])
    for field in schema.get("numeric_bounds", {}):
        row[field] = pd.to_numeric(row[field], errors="coerce").astype(float)
    logits = pipeline.decision_function(row)
    probs = temperature_probabilities(logits, temperature)[0]
    raw_probs = temperature_probabilities(logits)[0]
    index = int(np.argmax(probs))
    alternate_probabilities = probs.copy()
    alternate_probabilities[index] = -np.inf
    alternate = int(np.argmax(alternate_probabilities))
    transformed = pipeline["preprocess"].transform(row)
    vector = transformed.toarray()[0] if hasattr(transformed, "toarray") else transformed[0]
    contributions = pipeline["classifier"].coef_[index] * vector
    names = pipeline["preprocess"].get_feature_names_out()
    factors = sorted([{"feature": str(name), "logit_contribution": float(value)} for name, value in zip(names, contributions)], key=lambda x: -abs(x["logit_contribution"]))
    confidence = float(probs[index])
    difference = (pipeline["classifier"].coef_[index] - pipeline["classifier"].coef_[alternate]) * vector
    contrast_factors = sorted([{"feature": str(name), "logit_difference_contribution": float(value)} for name, value in zip(names, difference)],
                              key=lambda factor: -abs(factor["logit_difference_contribution"]))
    intercept_difference = float(pipeline["classifier"].intercept_[index] - pipeline["classifier"].intercept_[alternate])
    raw_difference = float(difference.sum() + intercept_difference)
    return {"suggestion": str(pipeline.classes_[index]) if confidence >= threshold else None,
        "predicted_label": str(pipeline.classes_[index]), "confidence": confidence,
        "raw_confidence": float(raw_probs[index]), "probabilities": {str(label): float(value) for label, value in zip(pipeline.classes_, probs)},
        "calibration_temperature": temperature, "abstention_threshold": threshold,
        "requires_clinician_review": True, "abstained": confidence < threshold,
        "factors": factors[:5], "intercept": float(pipeline["classifier"].intercept_[index]),
        "other_logit_contributions": float(sum(f["logit_contribution"] for f in factors[5:])),
        "class_logit": float(contributions.sum() + pipeline["classifier"].intercept_[index]),
        "explanation_method": "Exact raw feature contributions to predicted-class logit; calibration scales logits by 1/temperature, not causal effects",
        "contrastive": {"predicted_class": str(pipeline.classes_[index]), "alternative_class": str(pipeline.classes_[alternate]),
                        "factors": contrast_factors[:5], "intercept_difference": intercept_difference,
                        "other_logit_difference_contributions": float(sum(f["logit_difference_contribution"] for f in contrast_factors[5:])),
                        "raw_logit_difference": raw_difference, "calibrated_log_probability_ratio": raw_difference / temperature,
                        "method": "Exact predicted-minus-runner-up raw logit decomposition; divide total by temperature for calibrated log probability ratio",
                        "limitation": "Explains a fitted synthetic model, not biological mechanisms, treatment or a clinical counterfactual"},
        "reasons": ["Below research-selected confidence threshold"] if confidence < threshold else [],
        "plain_language": plain_language(names, difference, features, schema, str(pipeline.classes_[index]), str(pipeline.classes_[alternate])),
        "not_recorded": [field for field in schema.get("vital_features", []) if _is_missing(features.get(field))],
        "warning": WARNING, "model_suggestion_applied_automatically": False}


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, (float, np.floating)) and np.isnan(value))


def _factor_field(name: str, fields: list[str]) -> tuple[str, str]:
    """Map a transformed column back to (source field, kind)."""
    body = name.split("__", 1)[-1]
    if body.startswith("missingindicator_"):
        return body.removeprefix("missingindicator_"), "missing"
    if body in fields:
        return body, "value"
    for field in sorted(fields, key=len, reverse=True):
        if body.startswith(field + "_"):
            return field, "category"
    return body, "value"


def describe_input(field: str, features: dict, schema: dict) -> str:
    label = HUMAN_NAMES.get(field, field.replace("_", " "))
    value = features.get(field)
    if _is_missing(value):
        return f"{label} not recorded"
    if field in CATEGORIES:
        return f"{label}: {str(value).replace('_', ' ')}"
    median = schema.get("reference_profile", {}).get("numeric_quantiles", {}).get(field, {}).get("0.5")
    shown = f"{float(value):g}{'' if field == 'hour' else ' '}{UNITS.get(field, '')}".strip()
    if field == "hour":
        shown = f"{int(float(value)):02d}:00"
    if median is None:
        return f"{label} {shown}"
    relation = "above" if float(value) > median else "below" if float(value) < median else "at"
    reference = f"{int(median):02d}:00" if field == "hour" else f"{median:g}"
    return f"{label} {shown} ({relation} the training-data median of {reference})"


def plain_language(names, difference, features: dict, schema: dict, predicted: str, alternative: str) -> dict:
    """Selective, contrastive explanation (Miller 2019): the few inputs that most separated
    the suggested category from the runner-up, in words a clinician can check quickly.
    Aggregates one-hot and missingness columns back to their source field."""
    fields = schema_features(schema)
    totals: dict[str, float] = {}
    for name, value in zip(names, difference):
        if abs(float(value)) < 1e-9:
            continue
        field, _ = _factor_field(str(name), fields)
        totals[field] = totals.get(field, 0.0) + float(value)
    ranked = sorted(totals.items(), key=lambda item: -abs(item[1]))
    supporting = [describe_input(field, features, schema) for field, value in ranked if value > 0][:2]
    opposing = [describe_input(field, features, schema) for field, value in ranked if value < 0][:2]
    headline = f"Suggests {predicted} rather than {alternative}"
    if supporting:
        headline += ", mainly because of " + " and ".join(item[0].lower() + item[1:] for item in supporting)
    return {"headline": headline + ".", "predicted": predicted, "alternative": alternative,
            "supporting": supporting, "opposing": opposing,
            "caveat": "A pattern learned from synthetic training data, not a clinical rule. You decide the category."}


def evaluate_shadow(model_path: str, features: dict) -> dict:
    """Pure local inference. The caller owns access control, blinding and persistence.

    This function cannot update a visit, recommendation, clinician label or queue.
    Do not expose its result in a blinded study arm before independent assessment.
    """
    return explain_prediction(model_path, features)


def advisory_for_display(inference: dict) -> dict:
    """Abstention must not leak a withheld label through its explanation.

    Raw scores remain in private research artifacts/shadow records for evaluation.
    Ordinary advisory views never display the class or its attribution when the
    guard/threshold withholds a suggestion.
    """
    visible = dict(inference)
    if visible.get("abstained"):
        for key in ("predicted_label", "probabilities", "contrastive", "intercept", "plain_language",
                    "class_logit", "other_logit_contributions", "explanation_method"):
            visible.pop(key, None)
        visible["suggestion"] = None
        visible["factors"] = []
    return visible
