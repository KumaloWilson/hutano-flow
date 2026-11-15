from datetime import datetime, timezone, time, timedelta
from zoneinfo import ZoneInfo
from collections import Counter
import hashlib
import json
import numpy as np
from sqlalchemy import select
from app.models import Visit, ServiceEpisode, ServicePoint, ClinicianDecision, AuditEvent, QueuePolicy, Facility
from app.services.queue import rank_queue
from app.simulation.engine import summary


def effective_time(episode, field):
    value = episode.corrections[-1].corrected_values.get(field) if episode.corrections else None
    result = datetime.fromisoformat(value) if value else getattr(episode, field)
    return result.replace(tzinfo=timezone.utc) if result and result.tzinfo is None else result


def overview(db, facility_id, from_date=None, to_date=None):
    from fastapi import HTTPException
    if from_date and to_date and (from_date > to_date or (to_date-from_date).days>366):
        raise HTTPException(422,"Choose a chronological reporting range of at most 366 days")
    local_zone=ZoneInfo(db.get(Facility,facility_id).timezone)
    selection=select(Visit.id).where(Visit.facility_id==facility_id)
    if from_date: selection=selection.where(Visit.arrival_at>=datetime.combine(from_date,time(),local_zone).astimezone(timezone.utc))
    if to_date: selection=selection.where(Visit.arrival_at<datetime.combine(to_date+timedelta(days=1),time(),local_zone).astimezone(timezone.utc))
    visits = db.scalars(select(Visit).where(Visit.id.in_(selection))).all()
    episodes = db.scalars(select(ServiceEpisode).where(ServiceEpisode.facility_id == facility_id,ServiceEpisode.visit_id.in_(selection))).all()
    points = db.scalars(select(ServicePoint).where(ServicePoint.facility_id == facility_id)).all()
    policy = db.scalar(select(QueuePolicy).where(QueuePolicy.facility_id == facility_id, QueuePolicy.active.is_(True)))
    wait_limit = policy.config_json.get("long_wait_warning_minutes", 60) if policy else 60
    waits, services, provider, totals = [], [], [], []
    stages = []
    for point in points:
        rows = [e for e in episodes if e.service_point_id == point.id]
        stage_waits = [max(0, (effective_time(e, "started_at") - effective_time(e, "queued_at")).total_seconds() / 60) for e in rows if e.started_at and e.queued_at and e.status not in {"CANCELLED", "NO_SHOW", "TRANSFERRED"}]
        stage_service = [max(0, ((effective_time(e, "ended_at") - effective_time(e, "started_at")).total_seconds() - e.paused_seconds) / 60) for e in rows if e.started_at and e.ended_at and e.status == "COMPLETED"]
        waits.extend(stage_waits)
        services.extend(stage_service)
        stages.append({"name": point.name, "waiting": summary(stage_waits), "service": summary(stage_service),
            "completed": sum(e.status == "COMPLETED" for e in rows), "eligible_waiting_now": len(rank_queue(db, facility_id, point.id)),
            "long_wait_count": sum(w >= wait_limit for w in stage_waits), "capacity_now": point.capacity,
            "utilisation": None, "utilisation_note": "Historical staffing intervals not recorded; utilisation unavailable (simulation reports it separately)."})
    for visit in visits:
        starts = [effective_time(e, "started_at") for e in visit.episodes if e.service_point.type == "consultation" and e.started_at]
        arrival = visit.arrival_at.replace(tzinfo=timezone.utc) if visit.arrival_at.tzinfo is None else visit.arrival_at
        if starts:
            provider.append(max(0, (min(starts) - arrival).total_seconds() / 60))
        if visit.completed_at:
            totals.append(max(0, (visit.completed_at - visit.arrival_at).total_seconds() / 60))
    local_zone = ZoneInfo(db.get(Facility, facility_id).timezone)
    hours = Counter(v.arrival_at.astimezone(local_zone).hour for v in visits)
    decisions = db.scalars(select(ClinicianDecision).where(ClinicianDecision.facility_id == facility_id,ClinicianDecision.visit_id.in_(selection))).all()
    reviewed = [d for d in decisions if d.decision != "NO_MODEL"]
    overrides = sum(d.decision == "OVERRIDE" for d in reviewed)
    timing_rows = sorted([e.service_point.type, e.status, str(effective_time(e,"queued_at")), str(effective_time(e,"started_at")), str(effective_time(e,"ended_at")), e.paused_seconds] for e in episodes)
    visit_timings = sorted([str(v.arrival_at), str(v.completed_at), v.status] for v in visits)
    timing_hash = hashlib.sha256(json.dumps({"stages":timing_rows,"visits":visit_timings}, sort_keys=True).encode()).hexdigest()
    return {"research_label": "Synthetic/demo operational measurements", "visits_total": len(visits),
        "report_title": "Hutano Flow measured synthetic outpatient flow", "source_type": "SYNTHETIC_OPERATIONAL",
        "dataset_hash": timing_hash, "dataset_hash_basis": "Sorted effective stage and visit timing/status tuples, without identifiers; audited corrections affect this hash",
        "units": "minutes unless otherwise labelled", "model_version": None,
        "reporting_filter":{"from_date":from_date,"to_date":to_date,"timezone":str(local_zone),"basis":"Visits arriving during the selected local dates; queue counts remain the current snapshot"},
        "daily_activity":[{"day":day,"arrivals":sum(v.arrival_at.astimezone(local_zone).date().isoformat()==day for v in visits),"completed":sum(v.arrival_at.astimezone(local_zone).date().isoformat()==day and v.status=="COMPLETED" for v in visits)} for day in sorted({v.arrival_at.astimezone(local_zone).date().isoformat() for v in visits})],
        "active_visits": sum(v.status in {"REGISTERING", "AWAITING_TRIAGE", "TRIAGED", "ACTIVE", "ESCALATION_REQUIRED"} for v in visits),
        "completed_visits": sum(v.status == "COMPLETED" for v in visits), "waiting": summary(waits), "service": summary(services),
        "arrival_to_provider_minutes": summary(provider), "total_visit_minutes": summary(totals),
        "observation_period": {"from": min((v.arrival_at for v in visits), default=None), "through": max((v.completed_at or v.arrival_at for v in visits), default=None)},
        "service_points": stages, "arrivals_by_hour": [{"hour": h, "arrivals": hours[h]} for h in range(24)],
        "model_review": {"reviewed": len(reviewed), "overrides": overrides, "override_rate": overrides / len(reviewed) if reviewed else None},
        "policy_version": policy.version if policy else None,
        "timestamp_basis": "Latest audited episode correction where present; original timestamps retained in the journey timeline. Visit completion remains its original event.",
        "definitions": {"waiting": "started_at - queued_at; excludes cancelled, no-show and transferred stages",
            "service": "ended_at - started_at - accumulated pause seconds for completed episodes",
            "arrival_to_provider": "first consultation started_at - arrival_at",
            "throughput": "completed visits across displayed observation period", "queue_length": "eligible WAITING snapshot at report generation",
            "override_rate": "OVERRIDE / (ACCEPT + REJECT + OVERRIDE) clinician model reviews; manual no-model decisions excluded"}}
