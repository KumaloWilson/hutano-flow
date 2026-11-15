"""Pure, reproducible synthetic operational experiments; never clinical inference.

The estimand here is consultation-stage waiting, not the project's primary
whole-outpatient-journey estimand. No result changes a live queue or schedule.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import sklearn
from scipy.stats import t
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline


VERSION = "operations-study-v1"
HORIZON = 480.0
SERVICE_BOUND = 30.0
BASE_DATE = datetime(2026, 1, 5, 6, tzinfo=timezone.utc)
POLICIES = ["FIXED_ROOM", "POOLED_NEXT_AVAILABLE", "HISTORICAL_PLANNING", "LEARNED_PLANNING"]
DEFAULTS = {"seed": 2026, "training_days": 40, "test_days": 12, "arrivals_per_day": 50,
            "replications": 10, "shift_strength": 1.0, "missing_rate": 0.0}
BOUNDS = {"seed": (0, 2_000_000_000), "training_days": (28, 90), "test_days": (4, 30),
          "arrivals_per_day": (20, 150), "replications": (2, 40), "shift_strength": (0, 2),
          "missing_rate": (0, .5)}
FEATURES = ["queued_ahead", "estimated_ahead_work_minutes", "estimated_active_remaining_minutes",
            "free_servers", "currently_staffed_servers", "elapsed_active_minutes",
            "minute_of_day", "confirmed_category_index", "known_capacity_next_hour_minutes",
            "minutes_until_start_window", "known_outage", "queue_observation_missing"]


def normalize_operations_config(config: dict[str, Any]) -> dict[str, Any]:
    """Bound work and reject accidental/unknown research settings."""
    if not isinstance(config, dict) or set(config) - set(DEFAULTS):
        raise ValueError("Unknown operations-study configuration field")
    result = {**DEFAULTS, **config}
    for name, (low, high) in BOUNDS.items():
        value = result[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite number")
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        if not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        if name not in {"shift_strength", "missing_rate"} and int(value) != value:
            raise ValueError(f"{name} must be an integer")
        result[name] = float(value) if name in {"shift_strength", "missing_rate"} else int(value)
    return result


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _timestamp(day: int, minute: float) -> str:
    return (BASE_DATE + timedelta(days=day, minutes=float(minute))).isoformat()


def _seed(seed: int, stream: int, index: int = 0) -> int:
    # Explicit disjoint namespaces; no process-randomised Python hash.
    return int(np.random.SeedSequence([seed, stream, index]).generate_state(1)[0])


def _rates(day: int, config: dict, load: float = 1.) -> np.ndarray:
    """Declared synthetic weekday/hour structure and optional gradual demand shift."""
    profiles = np.array([[.19, .22, .20, .15, .09, .07, .05, .03],
                         [.08, .10, .13, .16, .19, .16, .11, .07],
                         [.10, .13, .16, .17, .15, .12, .10, .07]])
    profile = profiles[day % 7 % 3]
    weekday = [1.20, 1.02, .95, 1.10, 1., .85, .80][day % 7]
    trend = 1 + config["shift_strength"] * day / 160
    return profile * config["arrivals_per_day"] * weekday * trend * load


def _cohort(seed: int, rates: np.ndarray) -> list[dict]:
    rng = np.random.default_rng(seed)
    arrivals = sorted(float(hour * 60 + at) for hour, rate in enumerate(rates)
                      for at in rng.uniform(0, 60, int(rng.poisson(max(0, rate)))))
    return [{"patient_no": i + 1, "arrival": arrival,
             "duration": float(min(SERVICE_BOUND, max(1., rng.lognormal(np.log(12) - .45 ** 2 / 2, .45)))),
             "urgency": int(rng.integers(1, 6))} for i, arrival in enumerate(arrivals)]


def _schedules() -> list[dict]:
    schedules = []
    for name, starts in [("EARLY", [0, 0, 0]), ("BALANCED", [0, 60, 120]),
                         ("LATE", [120, 120, 120]), ("MORNING_PLUS", [0, 0, 120]),
                         ("AFTERNOON_PLUS", [0, 120, 120]), ("CENTRED", [60, 60, 60])]:
        rooms = [{"room": room + 1, "shift": [start, start + 360],
                  "break": [start + 150 + room * 15, start + 180 + room * 15]}
                 for room, start in enumerate(starts)]
        schedules.append({"name": name, "rooms": rooms, "paid_staff_minutes": 1080,
                          "planned_service_minutes": 990})
    return schedules


def _windows(schedule: dict, outage: bool) -> list[list[tuple[float, float]]]:
    windows = []
    for room in schedule["rooms"]:
        start, end = room["shift"]
        breaks = [room["break"]]
        if outage and room["room"] == 2:
            breaks.append([120, 180])
        cuts = sorted({start, end, *[max(start, min(end, cut)) for interval in breaks for cut in interval]})
        windows.append([(float(a), float(b)) for a, b in zip(cuts, cuts[1:])
                        if b > a and not any(left <= (a + b) / 2 < right for left, right in breaks)])
    return windows


def _simulate(cohort: list[dict], schedule: dict, *, day: int = 0, fixed: bool = False,
              outage: bool = False, history: np.ndarray | None = None,
              missing_rate: float = 0., missing_seed: int = 0) -> dict:
    """Finite day with hard category/FIFO order and no future-duration features.

    Every synthetic service is bounded at 30 min. A universal 30 min clearance
    guard before breaks/shift ends guarantees the same hard paid-hour budget;
    actual individual durations are NOT examined to decide eligibility/order.
    """
    history = np.asarray(history if history is not None else [12.], dtype=float)
    mean_service = float(history.mean())
    windows = _windows(schedule, outage)
    busy: list[dict | None] = [None] * 3
    queue: list[dict] = []
    records = {p["patient_no"]: {**p, "started": None, "ended": None, "room": None} for p in cohort}
    events: list[tuple[float, int, int]] = []
    for p in cohort:
        heapq.heappush(events, (p["arrival"], 1, p["patient_no"]))
    for intervals in windows:
        for start, end in intervals:
            for at in [start, end, max(start, end - SERVICE_BOUND)]:
                if 0 <= at < HORIZON:
                    heapq.heappush(events, (at, 2, -1))
    rng = np.random.default_rng(missing_seed)
    trace = []
    occupied = np.zeros(3)

    def open_now(room: int, now: float, clearance: bool = False) -> bool:
        return any(start <= now < end and (not clearance or now + SERVICE_BOUND <= end + 1e-9)
                   for start, end in windows[room])

    def order(item: dict) -> tuple:
        return item["urgency"], item["arrival"], item["patient_no"]

    def snapshot(item: dict, now: float) -> tuple[list[float | None], float]:
        rooms = [(item["patient_no"] - 1) % 3] if fixed else list(range(3))
        ahead = [other for other in queue if order(other) <= order(item)
                 and (not fixed or (other["patient_no"] - 1) % 3 == rooms[0])]
        residuals = []
        elapsed = []
        free = 0
        for room in rooms:
            current = busy[room]
            if current:
                age = now - current["started"]
                eligible_history = history[history > age]
                # Observed elapsed service and PRE-STUDY completed history only.
                residuals.append(float(np.mean(eligible_history - age)) if len(eligible_history) else max(0., SERVICE_BOUND - age))
                elapsed.append(age)
            elif open_now(room, now, True):
                residuals.append(0.)
                free += 1
        future = [max(0., start - now) for room in rooms for start, end in windows[room]
                  if end >= now + SERVICE_BOUND and max(start, now) + SERVICE_BOUND <= end]
        until_open = min(future) if future else HORIZON - now
        staffing = sum(open_now(room, now) for room in rooms)
        next_hour_capacity = sum(max(0., min(now + 60, end) - max(now, start))
                                 for room in rooms for start, end in windows[room])
        pool = list(residuals) or [until_open]
        for _ in ahead:
            at = int(np.argmin(pool))
            pool[at] += mean_service
        baseline = max(0., float(min(pool)))
        values = [float(len(ahead)), len(ahead) * mean_service, sum(residuals), float(free), float(staffing),
                  sum(elapsed), now, float(item["urgency"]), next_hour_capacity, until_open,
                  float(outage and 120 <= now < 180), 0.]
        if rng.random() < missing_rate:
            for index in [0, 1, 2, 5]:
                values[index] = None
            values[-1] = 1.
            baseline = float("nan")
        return values, baseline

    while events:
        now, kind, number = heapq.heappop(events)
        if now > HORIZON:
            break
        if kind == 0:
            finished = records[number]
            finished["ended"] = now
            busy[finished["room"] - 1] = None
            trace.append({"minute": now, "event": "COMPLETED", "patient_no": number})
        elif kind == 1:
            item = records[number]
            values, baseline = snapshot(item, now)
            item.update(features=values, baseline=baseline, predicted_at=_timestamp(day, now))
            queue.append(item)
            trace.append({"minute": now, "event": "ARRIVED", "patient_no": number})
        free = [room for room in range(3) if busy[room] is None and open_now(room, now, True)]
        while free and queue:
            pairs = [(room, item) for room in free for item in queue
                     if not fixed or (item["patient_no"] - 1) % 3 == room]
            if not pairs:
                break
            room, item = min(pairs, key=lambda pair: (order(pair[1]), pair[0]))
            queue.remove(item)
            free.remove(room)
            item.update(started=now, room=room + 1, outcome_available_at=_timestamp(day, now))
            busy[room] = item
            occupied[room] += item["duration"]
            heapq.heappush(events, (now + item["duration"], 0, item["patient_no"]))
            trace.append({"minute": now, "event": "STARTED", "patient_no": item["patient_no"],
                          "room": room + 1, "confirmed_category": f"P{item['urgency']}",
                          "eligible_queue_order": [p["patient_no"] for p in sorted(queue, key=order)]})
    rows = list(records.values())
    started = [r for r in rows if r["started"] is not None]
    completed = [r for r in rows if r["ended"] is not None]
    wait = [r["started"] - r["arrival"] for r in completed]
    accrued = [(r["started"] if r["started"] is not None else HORIZON) - r["arrival"] for r in rows]
    available = [sum(end - start for start, end in intervals) for intervals in windows]
    valid = all(any(left <= r["started"] and r["started"] + r["duration"] <= right + 1e-8
                    for left, right in windows[r["room"] - 1]) for r in started)
    return {"rows": rows, "trace": trace, "metrics": {
        "arrivals": len(rows), "completed": len(completed), "unserved": len(rows) - len(completed),
        "not_started": len(rows) - len(started), "mean_wait_minutes": float(np.mean(wait)) if wait else None,
        "p90_wait_minutes": float(np.quantile(wait, .9)) if wait else None,
        "all_arrival_accumulated_wait_mean_minutes": float(np.mean(accrued)) if accrued else None,
        "all_arrival_accumulated_wait_total_minutes": float(sum(accrued)),
        "low_urgency_long_waits": sum(value >= 60 and row["urgency"] >= 4 for row, value in zip(rows, accrued)),
        "by_confirmed_category": {f"P{u}": {"arrivals": sum(r["urgency"] == u for r in rows),
            "unserved": sum(r["urgency"] == u and r["ended"] is None for r in rows),
            "mean_accumulated_wait_minutes": float(np.mean([value for row, value in zip(rows, accrued) if row["urgency"] == u]))
                if any(r["urgency"] == u for r in rows) else None} for u in range(1, 6)},
        "paid_staff_minutes": 1080, "planned_service_minutes": 990,
        "available_service_minutes_after_outage": sum(available), "occupied_minutes": float(occupied.sum()),
        "utilisation": float(occupied.sum() / sum(available)) if sum(available) else None,
        "budget_and_window_constraints_valid": bool(valid and occupied.sum() <= sum(available) + 1e-8)}}


def _paired(differences: list[float]) -> dict:
    if not differences:
        return {"mean_difference_minutes": None, "paired_95_ci": None, "pairs": 0, "half_width_minutes": None}
    mean = float(np.mean(differences))
    margin = float(t.ppf(.975, len(differences) - 1) * np.std(differences, ddof=1) / np.sqrt(len(differences))) if len(differences) > 1 else None
    return {"mean_difference_minutes": mean, "paired_95_ci": [mean - margin, mean + margin] if margin is not None else None,
            "pairs": len(differences), "half_width_minutes": margin}


def _partition(rows: list[dict], boundary_day: int) -> list[dict]:
    boundary = _timestamp(boundary_day, 0)
    return [row for row in rows if row["started"] is not None and row["outcome_available_at"] < boundary]


def _prediction_report(rows: list[dict], point: np.ndarray, baseline: np.ndarray, margin: float) -> dict:
    target = np.asarray([r["started"] - r["arrival"] for r in rows])
    lo, hi = np.maximum(0., point - margin), point + margin
    return {"rows": len(rows), "mae_minutes": float(np.mean(abs(target - point))),
            "baseline_mae_minutes": float(np.mean(abs(target - baseline))),
            "interval_coverage": float(np.mean((target >= lo) & (target <= hi))),
            "mean_interval_width_minutes": float(np.mean(hi - lo))}


def _wait_study(config: dict, history: np.ndarray) -> dict:
    count = config["training_days"]
    a, b = int(count * .6), int(count * .8)
    schedule = _schedules()[1]
    all_days = []
    for day in range(count + config["test_days"]):
        load = [.75, 1., 1.25][day % 3]
        outage = day % 4 == 0
        cohort = _cohort(_seed(config["seed"], 10, day), _rates(day, config, load))
        result = _simulate(cohort, schedule, day=day, outage=outage, history=history,
                           missing_rate=config["missing_rate"], missing_seed=_seed(config["seed"], 11, day))
        for row in result["rows"]:
            row.update(day=day, load=load, outage=outage)
        all_days.append(result)
    partitions = {"training": (0, a), "selection": (a, b), "calibration": (b, count),
                  "test": (count, count + config["test_days"])}
    frames = {name: _partition([row for result in all_days[start:end] for row in result["rows"]], end)
              for name, (start, end) in partitions.items()}
    if min(len(rows) for rows in frames.values()) < 15:
        raise ValueError("Insufficient started consultation stages in a temporal partition")
    fallback = float(np.median([r["started"] - r["arrival"] for r in frames["training"]]))

    def x(rows):
        return np.asarray([[np.nan if v is None else v for v in r["features"]] for r in rows])

    def baseline(rows):
        return np.asarray([r["baseline"] if np.isfinite(r["baseline"]) else fallback for r in rows])

    def target(rows):
        return np.asarray([r["started"] - r["arrival"] for r in rows])

    model = make_pipeline(SimpleImputer(add_indicator=True), GradientBoostingRegressor(
        loss="absolute_error", n_estimators=50, max_depth=2, min_samples_leaf=12, random_state=config["seed"]))
    model.fit(x(frames["training"]), target(frames["training"]))
    selection = frames["selection"]
    candidate_mae = float(np.mean(abs(np.maximum(0., model.predict(x(selection))) - target(selection))))
    baseline_mae = float(np.mean(abs(baseline(selection) - target(selection))))
    selected = "gradient_boosting" if candidate_mae < baseline_mae else "queue_workload_baseline"

    def point(rows):
        return np.maximum(0., model.predict(x(rows))) if selected == "gradient_boosting" else baseline(rows)

    calibration = frames["calibration"]
    # Calibration is NEVER used for estimator selection or fitting.
    residual = abs(target(calibration) - point(calibration))
    nominal = .8
    rank = min(len(residual), math.ceil((len(residual) + 1) * nominal))
    margin = float(np.sort(residual)[rank - 1])
    test = frames["test"]
    test_point, test_base = point(test), baseline(test)
    slices = []
    for kind, values in [("load", [.75, 1., 1.25]), ("outage", [False, True]), ("queue_missing", [False, True])]:
        for value in values:
            indices = [i for i, row in enumerate(test) if (bool(row["features"][-1]) if kind == "queue_missing" else row[kind]) == value]
            if indices:
                slices.append({"slice": kind, "value": value,
                               **_prediction_report([test[i] for i in indices], test_point[indices], test_base[indices], margin)})
    traces = []
    for i, row in enumerate(test[:150]):
        traces.append({"day": row["day"], "synthetic_case": row["patient_no"], "predicted_at": row["predicted_at"],
                       "outcome_available_at": row["outcome_available_at"], "features": dict(zip(FEATURES, row["features"])),
                       "predicted_wait_minutes": float(test_point[i]), "baseline_minutes": float(test_base[i]),
                       "interval": [max(0., float(test_point[i]) - margin), float(test_point[i]) + margin],
                       "observed_wait_minutes": row["started"] - row["arrival"]})
    test_days = all_days[count:]
    dataset_hash = _hash([{key: row[key] for key in ["day", "patient_no", "arrival", "duration", "urgency"]}
                          for result in all_days for row in result["rows"]])
    return {"target": "Consultation queue entry to service start; minutes; started cases only for prediction accuracy",
            "dataset_hash": dataset_hash,
            "selected_estimator": selected, "selection_mae_minutes": {"gradient_boosting": candidate_mae, "queue_workload_baseline": baseline_mae},
            "features": FEATURES, "nominal_interval_coverage": nominal, "calibration_margin_minutes": margin,
            "test": _prediction_report(test, test_point, test_base, margin),
            "test_candidate_mae_minutes": float(np.mean(abs(np.maximum(0., model.predict(x(test))) - target(test)))),
            "partitions": {name: {"start": _timestamp(start, 0), "end_exclusive": _timestamp(end, 0), "days": end - start,
                "eligible_started_rows": len(frames[name]), "unstarted_excluded": sum(result["metrics"]["not_started"] for result in all_days[start:end]),
                "latest_outcome_available_at": max(row["outcome_available_at"] for row in frames[name])}
                for name, (start, end) in partitions.items()},
            "outcome_availability_purge": "Exclude labels not known strictly before the next partition starts; no day/case crosses partitions",
            "selection_rule": "Lowest selection-day MAE; freeze estimator, calibrate on later independent days, evaluate once on final days",
            "interval_method": "Absolute-residual split calibration; ceil((n+1)*0.8) order statistic; lower bound clipped at zero",
            "slices": slices, "prediction_traces": traces, "trace_limit": 150,
            "heldout_daily_metrics": [{"day": count + i, **result["metrics"]} for i, result in enumerate(test_days)],
            "all_arrival_outcomes": {"arrivals": sum(r["metrics"]["arrivals"] for r in test_days),
                "unserved": sum(r["metrics"]["unserved"] for r in test_days),
                "not_started": sum(r["metrics"]["not_started"] for r in test_days),
                "accumulated_wait_total_minutes": sum(r["metrics"]["all_arrival_accumulated_wait_total_minutes"] for r in test_days)},
            "limitations": ["Synthetic data; no claim about public patient ETA calibration", "Within-day dependence and temporal shift invalidate an automatic exchangeability/coverage guarantee",
                "Prediction error excludes unstarted/censored cases; all-arrival finite-horizon wait and counts are reported separately",
                "Historical residual duration uses only pre-study completed synthetic durations, never realised future service end",
                "Missing queue observations retain missing flags; baseline falls back to training-only median wait; no normal medical values imputed"]}


def _forecast_features(day: int, hour: int) -> list[float]:
    # Calendar and elapsed day are known at planning time. Weekday/hour
    # interactions permit a modest interpretable count regression, not oracle rates.
    return [float(day % 7 * 8 + hour == cell) for cell in range(56)] + [day / 30]


def _planning_study(config: dict, history: np.ndarray) -> dict:
    count = config["training_days"]
    observed = []
    for day in range(count + config["test_days"]):
        cohort = _cohort(_seed(config["seed"], 20, day), _rates(day, config))
        hourly = np.histogram([p["arrival"] for p in cohort], bins=np.arange(0, 481, 60))[0]
        observed.append(hourly)
    observed = np.asarray(observed)
    train_days = int(count * .75)
    x = np.asarray([_forecast_features(day, hour) for day in range(count) for hour in range(8)])
    y = observed[:count].reshape(-1)
    selection = []
    for alpha in [.01, .1, 1.]:
        candidate = PoissonRegressor(alpha=alpha, max_iter=300).fit(x[:train_days * 8], y[:train_days * 8])
        loss = float(np.mean(abs(candidate.predict(x[train_days * 8:]) - y[train_days * 8:])))
        selection.append((loss, alpha))
    _, alpha = min(selection)
    model = PoissonRegressor(alpha=alpha, max_iter=300).fit(x, y)
    historical = observed[:count].mean(axis=0)
    forecasts = {day: np.maximum(.01, model.predict(np.asarray([_forecast_features(day, hour) for hour in range(8)])))
                 for day in range(count, count + config["test_days"])}
    schedules = _schedules()
    chosen = {}
    diagnostics = []
    for day in forecasts:
        chosen[day] = {"FIXED_ROOM": schedules[0], "POOLED_NEXT_AVAILABLE": schedules[0]}
        for policy, rates in [("HISTORICAL_PLANNING", historical), ("LEARNED_PLANNING", forecasts[day])]:
            scores = []
            for schedule in schedules:
                outcomes = [_simulate(_cohort(_seed(config["seed"], 30, day * 4 + rep), rates), schedule,
                                      day=day, history=history)["metrics"] for rep in range(4)]
                objective = float(np.mean([r["all_arrival_accumulated_wait_mean_minutes"] for r in outcomes]))
                scores.append({"schedule": schedule["name"], "planning_mean_accumulated_wait_minutes": objective,
                               "planning_unserved_mean": float(np.mean([r["unserved"] for r in outcomes]))})
            best = min(scores, key=lambda row: (row["planning_mean_accumulated_wait_minutes"], row["planning_unserved_mean"], row["schedule"]))
            chosen[day][policy] = next(schedule for schedule in schedules if schedule["name"] == best["schedule"])
            diagnostics.append({"day": day, "policy": policy, "selected_schedule": best["schedule"],
                                "forecast_hourly_arrivals": rates.tolist(), "candidate_scores": scores})
    sensitivity = []
    replay = {}
    for label, load, outage in [("BASE", 1., False), ("LOW_LOAD", .75, False),
                                ("HIGH_LOAD", 1.25, False), ("ROOM_OUTAGE", 1., True)]:
        runs = {policy: [] for policy in POLICIES}
        hashes = []
        for rep in range(config["replications"]):
            day = count + rep % config["test_days"]
            cohort = _cohort(_seed(config["seed"], 40, rep), _rates(day, config, load))
            hashes.append(_hash(cohort))
            for policy in POLICIES:
                result = _simulate(cohort, chosen[day][policy], day=day, fixed=policy == "FIXED_ROOM", outage=outage, history=history)
                runs[policy].append({"replication": rep, "day": day, "schedule": chosen[day][policy]["name"], **result["metrics"]})
                if label == "BASE" and rep == 0:
                    replay[policy] = {"day": day, "schedule": chosen[day][policy], "events": result["trace"],
                        "cases": [{"synthetic_case": r["patient_no"], "confirmed_category": f"P{r['urgency']}",
                            "queued_at": _timestamp(day, r["arrival"]), "started_at": _timestamp(day, r["started"]) if r["started"] is not None else None,
                            "ended_at": _timestamp(day, r["ended"]) if r["ended"] is not None else None,
                            "room": r["room"], "accumulated_wait_minutes": (r["started"] if r["started"] is not None else HORIZON) - r["arrival"]}
                            for r in result["rows"]]}
        summaries = {}
        for policy, results in runs.items():
            def average(field):
                values = [r[field] for r in results if r[field] is not None]
                return float(np.mean(values)) if values else None
            summaries[policy] = {"mean_wait_minutes": average("mean_wait_minutes"),
                "mean_replication_p90_minutes": average("p90_wait_minutes"),
                "mean_all_arrival_accumulated_wait_minutes": average("all_arrival_accumulated_wait_mean_minutes"),
                "completed_mean": average("completed"), "unserved_mean": average("unserved"),
                "paid_staff_minutes": 1080, "planned_service_minutes": 990,
                "available_service_minutes_after_outage_mean": average("available_service_minutes_after_outage"),
                "utilisation_mean": average("utilisation"), "low_urgency_long_waits": sum(r["low_urgency_long_waits"] for r in results),
                "all_constraints_valid": all(r["budget_and_window_constraints_valid"] for r in results),
                "by_confirmed_category": {f"P{u}": {"unserved_mean": float(np.mean([r["by_confirmed_category"][f"P{u}"]["unserved"] for r in results])),
                    "mean_accumulated_wait_minutes": float(np.mean([r["by_confirmed_category"][f"P{u}"]["mean_accumulated_wait_minutes"] for r in results
                        if r["by_confirmed_category"][f"P{u}"]["mean_accumulated_wait_minutes"] is not None]))
                        if any(r["by_confirmed_category"][f"P{u}"]["mean_accumulated_wait_minutes"] is not None for r in results) else None} for u in range(1, 6)}}
        paired = {}
        for name, left, right in [("pooling_minus_fixed", "POOLED_NEXT_AVAILABLE", "FIXED_ROOM"),
                                   ("historical_planning_minus_pooling", "HISTORICAL_PLANNING", "POOLED_NEXT_AVAILABLE"),
                                   ("learned_minus_historical_planning", "LEARNED_PLANNING", "HISTORICAL_PLANNING")]:
            paired[name] = _paired([a["all_arrival_accumulated_wait_mean_minutes"] - b["all_arrival_accumulated_wait_mean_minutes"]
                                    for a, b in zip(runs[left], runs[right]) if a["all_arrival_accumulated_wait_mean_minutes"] is not None and b["all_arrival_accumulated_wait_mean_minutes"] is not None])
        sensitivity.append({"scenario": label, "load_multiplier": load, "outage": outage, "policies": summaries,
                            "paired_comparisons": paired, "input_hashes": hashes, "replication_metrics": runs})
    expected = np.asarray([forecasts[day] for day in forecasts])
    actual = observed[count:]
    return {"forecast": {"model": "Regularised Poisson count regression; weekday-hour interactions and calendar trend",
                "observed_hourly_dataset_hash": _hash(observed.tolist()),
                "selected_alpha": alpha, "selection_candidates": [{"alpha": value, "mae_arrivals_per_hour": loss} for loss, value in selection],
                "training_days": count, "heldout_test_days": config["test_days"],
                "test_mae_arrivals_per_hour": float(np.mean(abs(expected - actual))),
                "historical_hourly_baseline_mae": float(np.mean(abs(historical - actual))),
                "hourly_test_predictions": [{"day": day, "learned": forecasts[day].tolist(), "historical": historical.tolist(),
                                             "observed": observed[day].tolist()} for day in forecasts]},
            "allowed_schedules": schedules, "planning_decisions": diagnostics, "sensitivities": sensitivity, "replay": replay,
            "planning_objective": "Minimise mean finite-horizon accumulated waiting across ALL arrivals; ties: unserved, then schedule name",
            "planning_replications_per_candidate": 4,
            "selection_boundary": "Forecast fit/selection use development days only; four forecast-generated planning cohorts per candidate. Independent stream 40 is test-only; test outcomes never select schedules.",
            "replication_precision": {"requested": config["replications"], "default": 10,
                "rule": "Report paired t-interval half-width; choose final study replication count prospectively for desired precision. No post-hoc favourable-run filtering or guaranteed power.",
                "base_learned_minus_historical_half_width_minutes": sensitivity[0]["paired_comparisons"]["learned_minus_historical_planning"]["half_width_minutes"]},
            "limitations": ["Single consultation stage; does not replace primary whole-journey FCFS/urgency/hybrid experiment",
                "Fixed rooms preserve category order within each compatible room; pooled policies preserve global category then arrival order",
                "All schedules have 1080 paid staff minutes and 990 planned service minutes. Known outage removes overlapping availability, reported separately",
                "Synthetic service capped at 30 minutes; universal clearance guard before every break/end prevents overtime, deliberately sacrifices capacity, and never inspects a patient's realised duration",
                "Forecast models are evaluated even if worse than historical means; learned planning is not automatically preferred",
                "Four planning samples can overfit the synthetic model; independent held-out replications expose losses without guaranteeing real benefit",
                "Sensitivity schedules are frozen from base-demand planning, not retuned on test loads/outages",
                "Paired intervals quantify simulation uncertainty conditional on assumptions; no real-world causal or clinical-effect claim"]}


def run_operations_study(config: dict[str, Any]) -> dict[str, Any]:
    """Run both supporting experiments locally; deterministic and JSON-safe."""
    config = normalize_operations_config(config)
    rng = np.random.default_rng(_seed(config["seed"], 1))
    history = np.clip(rng.lognormal(np.log(12) - .45 ** 2 / 2, .45, 300), 1., SERVICE_BOUND)
    result = {"engine_version": VERSION, "config": config, "config_hash": _hash(config),
        "research_label": "SYNTHETIC OPERATIONAL RESEARCH — NOT CLINICAL EVIDENCE",
        "provenance": {"source": "SEEDED_SYNTHETIC_ONLY", "seed": config["seed"],
            "numpy_version": np.__version__, "sklearn_version": sklearn.__version__, "pre_study_completed_duration_samples": len(history),
            "pre_study_history_available_before": BASE_DATE.isoformat(),
            "pre_study_duration_hash": _hash(history.tolist()), "seed_streams": {"pre_study": 1, "wait_days": 10,
                "missing_observations": 11, "forecast_development_and_test_days": 20, "planning_only": 30, "planning_heldout_replications": 40}},
        "definitions": {"scope": "Supporting consultation-stage studies; original whole-outpatient-journey primary experiment remains unchanged",
            "waiting": "Consultation service start minus consultation queue arrival; excludes service",
            "accumulated_wait": "min(service start, 480-minute horizon) minus arrival, INCLUDING patients never started",
            "p90": "Mean of completed-case replication-specific P90s, not pooled P90",
            "unserved": "Arrived cases not completed by the finite 480-minute horizon",
            "urgency": "Synthetic clinician-confirmed P1–P5 inputs; never predicted or modified in these experiments",
            "calendar": "Deterministic synthetic days beginning 2026-01-05 06:00 UTC (08:00 Africa/Harare)",
            "service": "Independent bounded lognormal synthetic consultation duration: mean parameter 12 min, log SD .45, clipped 1–30 min",
            "demand": "Poisson hourly counts with declared weekday-hour profiles and optional gradual trend; not fitted real-clinic arrival process"},
        "priority_effect": "NONE", "live_schedule_mutations": False,
        "wait_prediction": _wait_study(config, history), "resource_planning": _planning_study(config, history),
        "limitations": ["Synthetic software experiments, not fieldwork or clinical validation", "Suggested arrangements require human review; no live staff or queue mutation",
            "Prediction accuracy does not itself cause shorter waits", "No patient-specific service duration is used to rank patients",
            "A distinction grade, clinical benefit, distribution-free temporal coverage or statistical power is not guaranteed"]}
    # Enforce strict serialization at the pure-computation boundary.
    json.dumps(result, allow_nan=False)
    return result
