"""Finite, reproducible diagnostics for synthetic advisory research, not safety gates.

All selection functions consume development partitions only. The callers freeze
their outputs before evaluating the final chronological holdout.
"""
from __future__ import annotations

import math
import numpy as np
from sklearn.metrics import log_loss


RELIABILITY_VERSION = "advisory-reliability-v1"
THRESHOLDS = [0.0, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.0]
ABSTENTION_COST = 0.35  # Dimensionless research utility, NOT a clinical threshold.


def temperature_probabilities(logits, temperature: float = 1.0) -> np.ndarray:
    values = np.asarray(logits, dtype=float) / temperature
    values -= values.max(axis=1, keepdims=True)
    weights = np.exp(values)
    return weights / weights.sum(axis=1, keepdims=True)


def fit_temperature(logits, actual, labels) -> dict:
    """One-parameter log-loss minimisation on the independent calibration set."""
    candidates = np.unique(np.r_[np.geomspace(0.25, 4.0, 161), 1.0])
    scores = [(float(log_loss(actual, temperature_probabilities(logits, t), labels=labels)), float(t))
              for t in candidates]
    loss, temperature = min(scores, key=lambda item: (item[0], abs(math.log(item[1]))))
    return {"temperature": temperature, "calibration_rows": len(actual),
            "calibration_log_loss": loss,
            "uncalibrated_calibration_log_loss": float(log_loss(actual, temperature_probabilities(logits), labels=labels)),
            "method": "Positive scalar temperature fitted on calibration-only logits by log loss",
            "search_bounds": [0.25, 4.0], "search_candidates": len(candidates),
            "at_search_boundary": temperature in (0.25, 4.0),
            "selection_does_not_consume_test_labels": True}


def wilson_interval(successes: int, n: int) -> list[float] | None:
    if not n:
        return None
    z = 1.959963984540054
    p = successes / n
    divisor = 1 + z * z / n
    midpoint = (p + z * z / (2 * n)) / divisor
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / divisor
    return [max(0.0, midpoint - half), min(1.0, midpoint + half)]


def probability_diagnostics(actual, probabilities, labels) -> dict:
    actual = np.asarray(actual)
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities)
    predicted = labels[probabilities.argmax(axis=1)]
    confidence = probabilities.max(axis=1)
    correct = predicted == actual
    bins = []
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        mask = (confidence >= low) & (confidence < high if index < 9 else confidence <= high)
        if mask.any():
            bins.append({"lower": low, "upper": high, "n": int(mask.sum()),
                         "mean_confidence": float(confidence[mask].mean()),
                         "fraction_correct": float(correct[mask].mean()),
                         "fraction_correct_ci95": wilson_interval(int(correct[mask].sum()), int(mask.sum()))})
    one_hot = (actual[:, None] == labels[None, :]).astype(float)
    return {"n": len(actual), "log_loss": float(log_loss(actual, probabilities, labels=labels)),
            "multiclass_brier_score": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
            "brier_definition": "Mean sum of squared class probability errors; range 0 to 2",
            "bins": bins,
            "expected_calibration_error": float(sum(abs(b["mean_confidence"] - b["fraction_correct"]) * b["n"] for b in bins) / len(actual)),
            "interpretation": "Scoring rules reflect discrimination and calibration; reliability bins are descriptive, not a clinical guarantee"}


def selective_summary(actual, probabilities, labels, threshold: float, eligible=None) -> dict:
    actual = np.asarray(actual)
    labels = np.asarray(labels)
    predicted = labels[np.asarray(probabilities).argmax(axis=1)]
    allowed = np.ones(len(actual), dtype=bool) if eligible is None else np.asarray(eligible, dtype=bool)
    accepted = allowed & (np.asarray(probabilities).max(axis=1) >= threshold)
    errors = accepted & (predicted != actual)
    n, accepted_n, error_n = len(actual), int(accepted.sum()), int(errors.sum())
    return {"threshold": float(threshold), "n": n, "eligible_n": int(allowed.sum()),
            "accepted_n": accepted_n, "abstained_n": n - accepted_n, "error_n": error_n,
            "coverage": accepted_n / n if n else None,
            "risk": error_n / accepted_n if accepted_n else None,
            "risk_ci95": wilson_interval(error_n, accepted_n),
            "coverage_ci95": wilson_interval(accepted_n, n)}


def risk_coverage(actual, probabilities, labels, eligible=None, thresholds=None) -> dict:
    actual = np.asarray(actual)
    probabilities = np.asarray(probabilities)
    eligible = np.ones(len(actual), dtype=bool) if eligible is None else np.asarray(eligible, dtype=bool)
    thresholds = THRESHOLDS if thresholds is None else thresholds
    return {"denominator": "All evaluation rows; missing/unseen/out-of-fit-range inputs abstain at every threshold",
            "overall": [selective_summary(actual, probabilities, labels, t, eligible) for t in thresholds],
            "per_reference_class": {str(label): [selective_summary(actual[actual == label], probabilities[actual == label], labels, t,
                                                                        eligible[actual == label]) for t in thresholds] for label in labels},
            "small_sample_warning": "Per-class counts and Wilson intervals retained; sparse synthetic groups do not establish fairness"}


def select_threshold(actual, probabilities, labels, eligible=None) -> dict:
    candidates = [selective_summary(actual, probabilities, labels, t, eligible) for t in THRESHOLDS]
    for candidate in candidates:
        candidate["research_cost"] = (candidate["error_n"] + ABSTENTION_COST * candidate["abstained_n"]) / candidate["n"]
    chosen = min(candidates, key=lambda row: (row["research_cost"], -row["coverage"], row["threshold"]))
    return {"threshold": chosen["threshold"], "selection_rows": len(actual), "selected": chosen,
            "candidates": candidates, "abstention_cost": ABSTENTION_COST,
            "objective": "Minimise (accepted synthetic-label errors + 0.35 * abstentions) / all threshold-selection rows; ties prefer coverage then lower threshold",
            "frozen_before_final_test": True,
            "warning": "Dimensionless predeclared engineering utility; not an approved clinical acceptance criterion"}


def bootstrap_intervals(actual, probabilities, labels, threshold, eligible, seed: int, resamples: int = 200,
                        reference_probabilities=None) -> dict:
    """Row-bootstrap uncertainty conditional on the fitted model; no retuning."""
    actual = np.asarray(actual)
    labels = np.asarray(labels)
    predicted = labels[np.asarray(probabilities).argmax(axis=1)]
    accepted = np.asarray(eligible, dtype=bool) & (np.asarray(probabilities).max(axis=1) >= threshold)
    rng = np.random.default_rng(seed)
    samples = {"macro_f1": [], "accuracy": [], "coverage": [], "selective_risk": []}
    score_rows = {}
    if reference_probabilities is not None:
        label_indices = np.array([int(np.flatnonzero(labels == label)[0]) for label in actual])
        one_hot = actual[:, None] == labels[None, :]
        calibrated_loss = -np.log(np.maximum(np.asarray(probabilities)[np.arange(len(actual)), label_indices], np.finfo(float).eps))
        raw_loss = -np.log(np.maximum(np.asarray(reference_probabilities)[np.arange(len(actual)), label_indices], np.finfo(float).eps))
        calibrated_brier = np.sum((np.asarray(probabilities) - one_hot) ** 2, axis=1)
        raw_brier = np.sum((np.asarray(reference_probabilities) - one_hot) ** 2, axis=1)
        score_rows = {"calibrated_log_loss": calibrated_loss, "calibrated_brier_score": calibrated_brier,
                      "calibrated_minus_raw_log_loss": calibrated_loss - raw_loss,
                      "calibrated_minus_raw_brier_score": calibrated_brier - raw_brier}
        samples.update({key: [] for key in score_rows})
    for _ in range(resamples):
        indices = rng.integers(0, len(actual), len(actual))
        y, p, a = actual[indices], predicted[indices], accepted[indices]
        scores = []
        for label in labels:
            tp = int(((y == label) & (p == label)).sum())
            denominator = int((y == label).sum() + (p == label).sum())
            scores.append(2 * tp / denominator if denominator else 0.0)
        samples["macro_f1"].append(float(np.mean(scores)))
        samples["accuracy"].append(float((y == p).mean()))
        samples["coverage"].append(float(a.mean()))
        if a.any():
            samples["selective_risk"].append(float((y[a] != p[a]).mean()))
        for key, values in score_rows.items():
            samples[key].append(float(values[indices].mean()))
    intervals = {key: np.quantile(values, [0.025, 0.975]).tolist() if values else None for key, values in samples.items()}
    accepted_n = int(accepted.sum())
    error_n = int(((actual != predicted) & accepted).sum())
    if error_n in (0, accepted_n):
        # Resampling cannot invent an unobserved outcome. A [0, 0] interval
        # from eleven error-free accepted cases would imply false precision.
        intervals["selective_risk"] = None
    return {"method": "Seeded percentile row bootstrap, conditional on fixed fitted model/calibrator/threshold",
            "resamples": resamples, "seed": seed,
            "intervals95": intervals,
            "selective_risk_wilson_interval95": wilson_interval(error_n, accepted_n),
            "boundary_policy": "Suppress boundary-degenerate percentile selective-risk intervals; Wilson interval remains primary, including zero observed errors",
            "valid_resamples": {key: len(values) for key, values in samples.items()},
            "limitations": "Assumes independent synthetic rows; does not cover model-selection uncertainty, repeated subjects or temporal dependence"}
