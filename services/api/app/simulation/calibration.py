"""Baseline measurement and simulation calibration (proposal §1.7, §1.8, §1.10, §2.1.1; ADR-035).

From an anonymous time-and-motion import this derives the measures the proposal lists
(total visit, wait and service per service point, arrivals by hour, queue length by hour),
a Little's Law sense-check, the bottleneck, and fitted inputs for the discrete-event
simulator. The simulator is then run under FCFS and compared with the measured baseline
before any policy comparison is interpreted.
"""
from __future__ import annotations

import io
import csv
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.simulation.engine import STAGES, generate_patients, simulate_once, summary

SNAPSHOT_MINUTES = 2
LITTLE_MIN_QUEUE = 0.2  # below this mean queue length the check is not assessable
SAMPLE_CAP = 5000


def _daily_peak_concurrency(stage_rows: pd.DataFrame) -> list[int]:
    peaks = []
    for _, day in stage_rows.groupby("day"):
        events = sorted([(t, 1) for t in day.started_at] + [(t, -1) for t in day.ended_at], key=lambda e: (e[0], e[1]))
        current = peak = 0
        for _, change in events:
            current += change
            peak = max(peak, current)
        peaks.append(peak)
    return peaks


def analyse_baseline(frame: pd.DataFrame, zone_name: str = "Africa/Harare") -> dict:
    zone = ZoneInfo(zone_name)
    frame = frame.copy()
    frame["local_arrival"] = frame.arrived_at.dt.tz_convert(zone)
    frame["day"] = frame.local_arrival.dt.date
    journeys = frame.groupby("journey_no").agg(arrived_at=("arrived_at", "first"), local_arrival=("local_arrival", "first"),
                                               day=("day", "first"), ended=("ended_at", "max"))
    days = sorted(journeys.day.unique())
    n_days = len(days)

    # Arrivals by local hour (mean per observed day) and the morning share (cf. Link et al. 2023).
    hours = journeys.local_arrival.dt.hour
    per_hour = hours.value_counts().sort_index()
    arrivals_by_hour = [{"hour": int(h), "mean_arrivals_per_day": round(float(per_hour.get(h, 0)) / n_days, 3)} for h in range(24) if per_hour.get(h, 0)]
    morning_share = float((hours < 12).mean()) if len(hours) else None

    # Snapshot headcounts every few minutes across each day's opening window.
    queue_by_hour: dict[str, list] = {}
    littles: dict[str, dict] = {}
    for stage in sorted(frame.stage.unique()):
        rows = frame[frame.stage == stage]
        snapshot_counts, hour_counts = [], {}
        lam_numerator = window_minutes = 0.0
        for day in days:
            day_journeys = journeys[journeys.day == day]
            day_rows = rows[rows.day == day]
            if day_journeys.empty:
                continue
            start, end = day_journeys.arrived_at.min(), day_journeys.ended.max()
            minutes = max((end - start).total_seconds() / 60, SNAPSHOT_MINUTES)
            window_minutes += minutes
            lam_numerator += len(day_rows)
            queued = np.array([t.value for t in day_rows.queued_at], dtype=np.int64)
            started = np.array([t.value for t in day_rows.started_at], dtype=np.int64)
            for offset in np.arange(0, minutes, SNAPSHOT_MINUTES):
                instant = (start + timedelta(minutes=float(offset))).value
                count = int(((queued <= instant) & (started > instant)).sum())
                snapshot_counts.append(count)
                local_hour = (start + timedelta(minutes=float(offset))).tz_convert(zone).hour
                hour_counts.setdefault(local_hour, []).append(count)
        queue_by_hour[str(stage)] = [{"hour": int(h), "mean_waiting": round(float(np.mean(v)), 3)} for h, v in sorted(hour_counts.items())]
        waits = ((rows.started_at - rows.queued_at).dt.total_seconds() / 60)
        if window_minutes and len(rows):
            lam = lam_numerator / window_minutes
            observed_l = float(np.mean(snapshot_counts)) if snapshot_counts else 0.0
            predicted_l = lam * float(waits.mean())
            ratio = observed_l / predicted_l if predicted_l else None
            assessable = predicted_l >= LITTLE_MIN_QUEUE
            littles[str(stage)] = {"arrival_rate_per_minute": round(lam, 5), "mean_wait_minutes": round(float(waits.mean()), 3),
                                   "observed_mean_queue_length": round(observed_l, 3), "lambda_times_w": round(predicted_l, 3),
                                   "ratio": round(ratio, 3) if ratio is not None else None, "assessable": assessable,
                                   "consistent": (abs(ratio - 1) <= .15) if assessable and ratio is not None else None}

    # Bottleneck and where the visit time goes.
    stage_means = frame.groupby("stage").apply(lambda g: float(((g.started_at - g.queued_at).dt.total_seconds() / 60).mean()), include_groups=False)
    total_wait = float(((frame.started_at - frame.queued_at).dt.total_seconds() / 60).sum())
    total_service = float(((frame.ended_at - frame.started_at).dt.total_seconds() / 60).sum())
    total_visit = float(((journeys.ended - journeys.arrived_at).dt.total_seconds() / 60).sum())
    bottleneck = str(stage_means.idxmax()) if len(stage_means) else None

    # Fitted simulation inputs (the simulator models registration, triage, consultation, pharmacy).
    # Robust opening window: ignore stray early/late records (1st–99th percentile of arrival hours).
    opening = int(np.floor(hours.quantile(.01))) if len(hours) else 8
    closing = int(np.ceil(hours.quantile(.99))) if len(hours) else 16
    hourly_rates = [max(.05, float(per_hour.get(h, 0)) / n_days) for h in range(opening, closing + 1)]
    service = {stage: ((g.ended_at - g.started_at).dt.total_seconds() / 60) for stage, g in frame.groupby("stage")}
    capacities = {}
    for stage in STAGES:
        rows = frame[frame.stage == stage]
        if len(rows):
            capacities[stage] = max(1, int(round(float(np.median(_daily_peak_concurrency(rows))))))
    consult = service.get("consultation", pd.Series([12.0]))
    cv = float(consult.std(ddof=1) / consult.mean()) if len(consult) > 1 and consult.mean() > 0 else .5
    with_pharmacy = frame[frame.stage == "pharmacy"].journey_no.nunique()
    inputs = {
        "days_observed": n_days, "patient_count_per_day": max(1, int(round(len(journeys) / n_days))),
        "opening_hour": opening, "hourly_rates": [round(r, 3) for r in hourly_rates],
        "arrival_rate_per_hour": round(float(np.mean(hourly_rates)), 3),
        "mean_service_minutes": round(float(consult.mean()), 3),
        "service_tail": round(float(np.sqrt(np.log(1 + cv ** 2))), 3),
        "stage_means": {stage: round(float(service[stage].mean()), 3) for stage in ("registration", "triage", "pharmacy") if stage in service},
        "stage_capacities": capacities, "consultation_servers": capacities.get("consultation", 1),
        "pharmacy_probability": round(with_pharmacy / max(1, len(journeys)), 3),
        "excluded_stages": sorted(set(frame.stage.unique()) - set(STAGES)),
        "method": "Hourly arrival means per observed day from the first to last arrival hour; consultation service lognormal with CV-matched tail; "
                  "capacity = median across days of peak concurrent services at each stage; one simulated replication = one clinic day.",
    }

    def sample(values):
        values = np.round(np.sort(np.asarray(values, dtype=float)), 1)
        if len(values) > SAMPLE_CAP:
            values = values[np.linspace(0, len(values) - 1, SAMPLE_CAP).astype(int)]
        return values.tolist()

    consult_rows = frame[frame.stage == "consultation"]
    return {
        "days_observed": n_days,
        "arrivals_by_hour": arrivals_by_hour, "morning_arrival_share": round(morning_share, 4) if morning_share is not None else None,
        "queue_length_by_hour": queue_by_hour,
        "littles_law": {"stages": littles, "snapshot_interval_minutes": SNAPSHOT_MINUTES,
                        "method": "Observed L = mean headcount waiting at snapshots across each day's window; λ = stage entries per window minute; "
                                  "W = mean measured wait. A ratio far from 1 suggests missing or inconsistent timestamps.",
                        "all_consistent": bool(littles) and all(item["consistent"] is not False for item in littles.values()),
                        "not_assessable": [stage for stage, item in littles.items() if not item["assessable"]]},
        "bottleneck_stage": bottleneck,
        "time_share": {"waiting": round(total_wait / total_visit, 4) if total_visit else None,
                       "in_service": round(total_service / total_visit, 4) if total_visit else None,
                       "definition": "Share of summed visit time spent waiting vs being served (cf. hours waited for minutes of care)"},
        "simulation_inputs": inputs,
        # Anonymous, unlinked samples (rounded, sorted, no journey numbers) for inferential tests (ADR-035).
        "wait_samples": {str(stage): sample((g.started_at - g.queued_at).dt.total_seconds() / 60) for stage, g in frame.groupby("stage")},
        "arrival_to_provider_sample": sample((consult_rows.started_at - consult_rows.arrived_at).dt.total_seconds() / 60),
    }


def calibrated_config(report: dict) -> dict:
    inputs = report.get("simulation_inputs")
    if not inputs:
        raise ValueError("This baseline was imported before calibration support; import it again to derive simulation inputs")
    return {"patient_count": inputs["patient_count_per_day"], "servers": inputs["consultation_servers"],
            "arrival_rate_per_hour": inputs["arrival_rate_per_hour"], "hourly_rates": inputs["hourly_rates"],
            "mean_service_minutes": inputs["mean_service_minutes"], "service_tail": inputs["service_tail"],
            "stage_means": inputs["stage_means"], "stage_capacities": inputs["stage_capacities"],
            "pharmacy_probability": inputs["pharmacy_probability"]}


def validation_target(report: dict) -> dict:
    return {"stages": report.get("stages", {}), "arrival_to_provider_minutes": report.get("arrival_to_provider_minutes"),
            "total_visit_minutes": report.get("total_visit_minutes")}


# A walk-in clinic day loosely shaped like the Harare polyclinic pattern (Link et al. 2023):
# most arrivals in the first morning hours, a single registration desk and short consultations.
EXAMPLE_HOURLY = [12, 10, 7, 3, 1.5, 1, .6, .5, .4, .3]


def synthetic_baseline_csv(days: int = 15, seed: int = 2026, open_hour: int = 7, zone_name: str = "Africa/Harare",
                           start: datetime | None = None) -> str:
    """Generate an anonymous, explicitly SYNTHETIC time-and-motion CSV by running the FCFS
    simulator — useful for demonstrating import, calibration and validation end to end."""
    zone = ZoneInfo(zone_name)
    first = (start or datetime.now(timezone.utc)).astimezone(zone).date() - timedelta(days=days + 1)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["journey_no", "stage", "arrived_at", "queued_at", "started_at", "ended_at"])
    journey = 0
    for index in range(days):
        day = first + timedelta(days=index)
        opening = datetime.combine(day, time(open_hour), zone)
        # Draw generously, then keep only arrivals inside opening hours (a Poisson day, no stragglers).
        drawn = generate_patients(seed + index, 80, 6., 9., pharmacy_probability=.85, hourly_rates=EXAMPLE_HOURLY,
                                  stage_means={"registration": 5.0, "triage": 4.5, "pharmacy": 2.5})
        patients = [p for p in drawn if p.arrival < len(EXAMPLE_HOURLY) * 60]
        run = simulate_once(patients, "FCFS", 2, {"registration": 1, "triage": 1, "consultation": 2, "pharmacy": 1})
        for patient in patients:
            trace = run["traces"].get(str(patient.patient_no))
            if not trace:
                continue
            journey += 1
            arrived = opening + timedelta(minutes=patient.arrival)
            for step in trace:
                writer.writerow([journey, step["stage"], arrived.isoformat(timespec="seconds"),
                                 (opening + timedelta(minutes=step["queued"])).isoformat(timespec="seconds"),
                                 (opening + timedelta(minutes=step["started"])).isoformat(timespec="seconds"),
                                 (opening + timedelta(minutes=step["ended"])).isoformat(timespec="seconds")])
    return out.getvalue()


__all__ = ["analyse_baseline", "calibrated_config", "validation_target", "synthetic_baseline_csv", "summary"]
