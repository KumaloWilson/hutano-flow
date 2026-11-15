"""One-way, synthetic-only FHIR R4-shaped export (spec section 14, ADR-031).

This is an export *adapter*, not a FHIR server and not a compliance claim. Mappings:
  Patient     -> FHIR Patient     (internal UUID only; no pseudonym, gender, birth decade as extension)
  Visit       -> FHIR Encounter   (class AMB; status mapped below; one location per service episode)
  Observation -> FHIR Observation (local code system; no LOINC binding has been approved)

Clinician-confirmed urgency labels are exported as a local Encounter.priority code, labelled
as a neutral research category rather than a clinical acuity scale (ADR-002).
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Facility, Observation, Patient, ServiceEpisode, User, Visit, utcnow
from app.security import require_roles
from app.services.queue import latest_urgency

router = APIRouter(prefix="/api/v1/interop/fhir")
DB = Depends(get_db, scope="function")

LOCAL = "https://hutano-flow.invalid/fhir"
SYNTHETIC_TAG = {"system": f"{LOCAL}/CodeSystem/data-provenance", "code": "synthetic", "display": "Synthetic demonstration data"}
ENCOUNTER_STATUS = {
    "REGISTERING": "arrived", "AWAITING_TRIAGE": "triaged", "TRIAGED": "triaged", "ACTIVE": "in-progress",
    "ESCALATION_REQUIRED": "in-progress", "COMPLETED": "finished", "CANCELLED": "cancelled",
    "LEFT_WITHOUT_SERVICE": "cancelled", "CREATED": "planned",
}
LOCATION_STATUS = {"WAITING": "planned", "CALLED": "planned", "IN_SERVICE": "active", "PAUSED": "active"}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return value.isoformat()


def patient_resource(patient: Patient) -> dict:
    resource = {"resourceType": "Patient", "id": str(patient.id), "meta": {"tag": [SYNTHETIC_TAG]}, "active": True}
    if patient.age_band:
        resource["extension"] = [{"url": f"{LOCAL}/StructureDefinition/age-band", "valueString": patient.age_band}]
    return resource


def encounter_resource(db: Session, visit: Visit) -> dict:
    urgency = latest_urgency(db, visit.id)
    locations = []
    for episode in visit.episodes:
        period = {k: v for k, v in {"start": _iso(episode.started_at or episode.queued_at), "end": _iso(episode.ended_at)}.items() if v}
        locations.append({
            "location": {"display": episode.service_point.name},
            "status": "completed" if episode.status in {"COMPLETED", "TRANSFERRED"} else LOCATION_STATUS.get(episode.status, "completed"),
            **({"period": period} if period else {}),
        })
    resource = {
        "resourceType": "Encounter", "id": str(visit.id), "meta": {"tag": [SYNTHETIC_TAG]},
        "identifier": [{"system": f"{LOCAL}/display-number", "value": visit.public_token}],
        "status": ENCOUNTER_STATUS.get(visit.status, "unknown"),
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
        "subject": {"reference": f"Patient/{visit.patient_id}"},
        "period": {k: v for k, v in {"start": _iso(visit.arrival_at), "end": _iso(visit.completed_at)}.items() if v},
        "location": locations,
    }
    if urgency:
        resource["priority"] = {"coding": [{"system": f"{LOCAL}/CodeSystem/neutral-research-category", "code": urgency,
                                            "display": f"Clinician-confirmed neutral category {urgency}"}]}
    if visit.entry_mode == "RETROSPECTIVE":
        resource["meta"]["tag"].append({"system": f"{LOCAL}/CodeSystem/entry-mode", "code": "retrospective",
                                        "display": "Transcribed from paper downtime record"})
    return resource


def observation_resource(item: Observation, visit: Visit) -> dict:
    resource = {
        "resourceType": "Observation", "id": str(item.id), "meta": {"tag": [SYNTHETIC_TAG]}, "status": "final",
        "code": {"coding": [{"system": f"{LOCAL}/CodeSystem/observation-field", "code": item.field_code}], "text": item.field_code},
        "subject": {"reference": f"Patient/{visit.patient_id}"}, "encounter": {"reference": f"Encounter/{visit.id}"},
        "effectiveDateTime": _iso(item.observed_at),
    }
    if item.value is None:
        resource["dataAbsentReason"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/data-absent-reason", "code": "unknown"}]}
    else:
        try:
            resource["valueQuantity"] = {"value": float(item.value), **({"unit": item.unit} if item.unit else {})}
        except ValueError:
            resource["valueString"] = item.value
    return resource


def validate_bundle(bundle: dict) -> list[str]:
    """Structural checks only (required elements, reference integrity). Not a FHIR validator."""
    problems = []
    if bundle.get("resourceType") != "Bundle" or bundle.get("type") != "collection":
        problems.append("Bundle must be a collection")
    present = {f"{e['resource']['resourceType']}/{e['resource']['id']}" for e in bundle.get("entry", [])}
    required = {"Patient": ["id"], "Encounter": ["id", "status", "class", "subject"], "Observation": ["id", "status", "code", "subject"]}
    for entry in bundle.get("entry", []):
        resource = entry["resource"]
        for field in required.get(resource["resourceType"], []):
            if field not in resource:
                problems.append(f"{resource['resourceType']}/{resource.get('id')} missing {field}")
        for key in ("subject", "encounter"):
            ref = resource.get(key, {}).get("reference")
            if ref and ref not in present:
                problems.append(f"{resource['resourceType']}/{resource['id']} references missing {ref}")
        if entry.get("fullUrl") != f"urn:uuid:{resource['id']}":
            problems.append(f"{resource['resourceType']}/{resource['id']} has an inconsistent fullUrl")
    return problems


def build_bundle(db: Session, visits: list[Visit]) -> dict:
    if any(not v.patient.synthetic_flag for v in visits):
        raise HTTPException(409, "FHIR export is restricted to synthetic records in this build")
    entries, seen = [], set()
    for visit in visits:
        if visit.patient_id not in seen:
            seen.add(visit.patient_id)
            entries.append(patient_resource(visit.patient))
        entries.append(encounter_resource(db, visit))
        for item in db.scalars(select(Observation).where(Observation.visit_id == visit.id).order_by(Observation.observed_at)):
            entries.append(observation_resource(item, visit))
    bundle = {
        "resourceType": "Bundle", "id": str(uuid.uuid4()), "type": "collection", "timestamp": _iso(utcnow()),
        "meta": {"tag": [SYNTHETIC_TAG]},
        "entry": [{"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in entries],
    }
    problems = validate_bundle(bundle)
    if problems:
        raise HTTPException(500, "Export failed structural validation")
    return bundle


@router.get("/Encounter/{visit_id}")
def export_visit(visit_id: uuid.UUID, user: User = Depends(require_roles("ADMIN")), db: Session = DB):
    visit = db.scalar(select(Visit).where(Visit.id == visit_id, Visit.facility_id == user.facility_id))
    if not visit:
        raise HTTPException(404, "Visit not found")
    return jsonable_encoder(build_bundle(db, [visit]))


@router.get("/export")
def export_range(user: User = Depends(require_roles("ADMIN")), db: Session = DB,
                 from_date: date = Query(...), to_date: date = Query(...)):
    if to_date < from_date or (to_date - from_date).days > 31:
        raise HTTPException(422, "Export at most 31 local days at a time")
    zone = ZoneInfo(db.get(Facility, user.facility_id).timezone)
    start = datetime.combine(from_date, time(), zone).astimezone(timezone.utc)
    end = datetime.combine(to_date + timedelta(days=1), time(), zone).astimezone(timezone.utc)
    visits = db.scalars(select(Visit).where(Visit.facility_id == user.facility_id, Visit.arrival_at >= start,
                                            Visit.arrival_at < end).order_by(Visit.arrival_at).limit(2000)).all()
    bundle = build_bundle(db, list(visits))
    bundle["meta"]["tag"].append({"system": f"{LOCAL}/CodeSystem/export-caveat", "code": "not-certified",
                                  "display": "FHIR R4-shaped research export; not validated against a profile or certified"})
    return jsonable_encoder(bundle)
