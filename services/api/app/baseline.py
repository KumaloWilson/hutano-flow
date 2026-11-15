"""Strict anonymous time-motion import and aggregate-only research reporting."""
import csv
import hashlib
import io
import json
import uuid
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
import pandas as pd
from app.commands import CommandRoute
from app.config import settings
from app.database import get_db
from app.models import Dataset, User
from app.security import require_roles, rate_limiter
from app.services.audit import record_audit
from app.simulation.engine import summary

router = APIRouter(prefix="/api/v1/research/baseline", route_class=CommandRoute)
COLUMNS = {"journey_no", "stage", "arrived_at", "queued_at", "started_at", "ended_at"}


def inspect_baseline(raw: bytes, mapping: dict):
    frame = pd.read_csv(io.BytesIO(raw)).rename(columns=mapping)
    if set(frame.columns) != COLUMNS or len(frame.columns) != len(COLUMNS):
        raise ValueError("Exactly journey_no, stage, arrived_at, queued_at, started_at, ended_at are permitted")
    if not 1 <= len(frame) <= 20000 or frame.isna().any().any():
        raise ValueError("Use 1–20,000 complete timestamp rows")
    ids = pd.to_numeric(frame.journey_no, errors="raise")
    if not ((ids >= 1) & (ids <= 1000000) & (ids % 1 == 0)).all():
        raise ValueError("journey_no must be an anonymous integer sequence, never a patient identifier")
    if not frame.stage.isin(["registration", "triage", "consultation", "pharmacy", "laboratory", "discharge"]).all():
        raise ValueError("Unknown service stage")
    for field in ["arrived_at", "queued_at", "started_at", "ended_at"]:
        if not frame[field].astype(str).str.contains(r"(?:Z|[+-]\d{2}:\d{2})$", regex=True).all():
            raise ValueError("Every timestamp must include a UTC offset")
        frame[field] = pd.to_datetime(frame[field], utc=True, errors="raise")
    if not ((frame.queued_at >= frame.arrived_at) & (frame.started_at >= frame.queued_at) & (frame.ended_at >= frame.started_at)).all():
        raise ValueError("Timestamp chronology is invalid")
    if frame.duplicated(["journey_no", "stage"]).any():
        raise ValueError("Duplicate journey/stage rows")
    for _, journey in frame.groupby("journey_no"):
        if journey.arrived_at.nunique() != 1:
            raise ValueError("Journey arrival times must match across stages")
        ordered = journey.sort_values("started_at")
        if any(a > b for a, b in zip(ordered.ended_at.iloc[:-1], ordered.queued_at.iloc[1:])):
            raise ValueError("Journey service stages overlap")
    frame["wait"] = (frame.started_at - frame.queued_at).dt.total_seconds() / 60
    frame["service"] = (frame.ended_at - frame.started_at).dt.total_seconds() / 60
    consult = frame[frame.stage == "consultation"]
    total = [(g.ended_at.max() - g.arrived_at.min()).total_seconds() / 60 for _,g in frame.groupby("journey_no")]
    return frame, {"row_count": len(frame), "journeys": int(frame.journey_no.nunique()),
        "waiting_minutes": summary(frame.wait.tolist()), "service_minutes": summary(frame.service.tolist()),
        "arrival_to_provider_minutes": summary(((consult.started_at - consult.arrived_at).dt.total_seconds() / 60).tolist()),
        "total_visit_minutes": summary(total),
        "stages": {str(stage): {"waiting_minutes": summary(g.wait.tolist()), "service_minutes": summary(g.service.tolist())} for stage,g in frame.groupby("stage")},
        "observation_period": [frame.arrived_at.min().isoformat(), frame.ended_at.max().isoformat()],
        "definitions": "Waiting=start-queued; service=end-start; total=last end-arrival. No pause data in this import.",
        "preview": [{"stage": str(r.stage), "wait_minutes": r.wait, "service_minutes": r.service} for r in frame.head(5).itertuples()]}


@router.post("/import", status_code=201)
async def import_baseline(file: UploadFile = File(...), name: str = Form(...), provenance: str = Form(...),
    column_mapping: str = Form("{}"), preview_only: bool = Form(False), synthetic_flag: bool = Form(True),
    user: User = Depends(require_roles("ADMIN", "RESEARCHER")), db: Session = Depends(get_db, scope="function"), key: str = Header(alias="Idempotency-Key")):
    rate_limiter.check(f"baseline:{user.id}", 10, 300)
    if not synthetic_flag or not 5 <= len(provenance) <= 500 or not 3 <= len(name) <= 120:
        raise HTTPException(422, "Synthetic-only import requires a name and provenance")
    raw = await file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(413, "File exceeds size limit")
    try:
        mapping = json.loads(column_mapping)
        if not isinstance(mapping, dict) or any(v not in COLUMNS for v in mapping.values()):
            raise ValueError("Invalid column mapping")
        frame, report = inspect_baseline(raw, mapping)
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(422, str(error)) from error
    digest = hashlib.sha256(raw).hexdigest()
    if preview_only:
        return {"preview_only": True, "dataset_hash": digest, **report}
    dataset = Dataset(facility_id=user.facility_id, name=name, source_type="SYNTHETIC_BASELINE", dataset_hash=digest,
        consent_basis_note=provenance, schema_json={"columns": sorted(COLUMNS), "report": report, "label_source": "SYNTHETIC"},
        row_count=len(frame), synthetic_flag=True)
    db.add(dataset)
    db.flush()
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="baseline.imported", object_type="Dataset", object_id=dataset.id,
        correlation_id=key, new={"dataset_hash": digest, "rows": len(frame)})
    return {"id": str(dataset.id), "dataset_hash": digest, **report}
