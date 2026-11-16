"""Model inputs from routinely collected visit data (proposal Objective 2, ADR-033).

The advisory reads what reception and triage already record: the patient's age band, the
visit type, how they arrived, the local arrival hour and the latest vital signs entered for
this visit. Values a clinician has typed into the triage form but not yet saved can be
supplied for the same request. Every value is returned with its source, and nothing is
filled in: a vital sign that was not recorded is reported as such.
"""
from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.pipeline import CATEGORIES, CONTEXT_FEATURES, RECORDING_RANGES, VITAL_FEATURES
from app.models import Facility, Observation, Visit

# Registration visit types mapped onto the model's visit categories.
VISIT_TYPE_MAP = {"walk_in": "new", "new": "new", "scheduled": "new", "follow_up": "follow_up", "referral": "referral"}


def visit_inputs(db: Session, visit: Visit, entered: dict | None = None) -> tuple[dict, dict]:
    """Return (values, provenance) for every schema-v3 feature."""
    values: dict = {}
    source: dict = {}
    band = visit.patient.age_band if visit.patient else None
    values["age_band"] = band if band in CATEGORIES["age_band"] else None
    source["age_band"] = "registration" if values["age_band"] else "not recorded"
    values["visit_type"] = VISIT_TYPE_MAP.get(visit.visit_type)
    source["visit_type"] = "registration" if values["visit_type"] else "not recorded"
    values["arrival_mode"] = "referred" if visit.visit_type == "referral" else "walk_in"
    source["arrival_mode"] = "registration"
    arrival = visit.arrival_at if visit.arrival_at.tzinfo else visit.arrival_at.replace(tzinfo=timezone.utc)
    zone = ZoneInfo(db.get(Facility, visit.facility_id).timezone)
    values["hour"] = arrival.astimezone(zone).hour
    source["hour"] = "arrival time"
    recorded = db.scalars(select(Observation).where(Observation.visit_id == visit.id, Observation.field_code.in_(VITAL_FEATURES))
                          .order_by(Observation.observed_at)).all()
    latest = {}
    for item in recorded:
        if item.value is not None:
            latest[item.field_code] = item.value
    for field in VITAL_FEATURES:
        typed = (entered or {}).get(field)
        if typed is not None:
            values[field], source[field] = float(typed), "entered at triage (unsaved)"
        elif field in latest:
            try:
                values[field], source[field] = float(latest[field]), "recorded observation"
            except ValueError:
                values[field], source[field] = None, "not recorded"
        else:
            values[field], source[field] = None, "not recorded"
    return values, source


def check_recording_ranges(observations: dict) -> list[str]:
    """Data-entry plausibility only — rejects impossible values, not abnormal ones (ADR-002)."""
    problems = []
    for field, value in observations.items():
        if value is None or field not in RECORDING_RANGES:
            continue
        low, high = RECORDING_RANGES[field]
        if not low <= float(value) <= high:
            problems.append(f"{field.replace('_', ' ')} {value} is outside the recordable range {low}–{high}")
    return problems


__all__ = ["visit_inputs", "check_recording_ranges", "CONTEXT_FEATURES", "VITAL_FEATURES"]
