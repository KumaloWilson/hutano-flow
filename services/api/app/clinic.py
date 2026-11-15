"""Facility snapshots and role-filtered fictional demonstration guidance."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Facility, Visit, ServiceEpisode, ServicePoint, DemoSession, Job, ModelVersion, utcnow
from app.security import CurrentUser, role_names
from app.access import allowed_services, OPERATIONAL_ROLES, can_access_visit
from app.services.workflow import ACTIVE_VISIT_STATES
from app.services.queue import rank_queue

router=APIRouter(prefix="/api/v1/clinic")


class ClinicSnapshot(BaseModel):
    facility: dict[str, Any]
    generated_at: datetime
    day: str
    counts: dict[str, int]
    services: list[dict[str, Any]]
    hourly_arrivals: list[dict[str, int]]
    demonstration: dict[str, Any] | None


@router.get("/snapshot",response_model=ClinicSnapshot)
def snapshot(user:CurrentUser,db:Session=Depends(get_db,scope="function")):
    facility=db.get(Facility,user.facility_id)
    now=utcnow();day=now.astimezone(ZoneInfo(facility.timezone)).date()
    start=datetime.combine(day,time(),ZoneInfo(facility.timezone)).astimezone(timezone.utc)
    end=start+timedelta(days=1)
    roles=role_names(user);aggregate=bool(roles&{"ADMIN","MANAGER","RESEARCHER"})
    services=allowed_services(user) if roles&OPERATIONAL_ROLES and not aggregate else None
    # Totals need timestamps and states, not patient/episode ORM graphs.
    visit_query=select(Visit.id,Visit.arrival_at,Visit.completed_at,Visit.status).where(Visit.facility_id==facility.id)
    if services is not None and not roles&{"RECEPTIONIST","CLINICIAN","TRIAGE_NURSE"}:
        visit_query=visit_query.where(Visit.episodes.any(ServiceEpisode.service_point.has(ServicePoint.type.in_(services))))
    visits=db.execute(visit_query).all()
    active=[v for v in visits if v.status in ACTIVE_VISIT_STATES]
    points=db.scalars(select(ServicePoint).where(ServicePoint.facility_id==facility.id).order_by(ServicePoint.name)).all()
    pathway={kind:i for i,kind in enumerate(["registration","triage","consultation","laboratory","pharmacy","discharge"])}
    points.sort(key=lambda p:pathway.get(p.type,99))
    if services is not None: points=[p for p in points if p.type in services]
    stages=[]
    for point in points:
        ranked=rank_queue(db,facility.id,point.id)
        occupied=db.scalar(select(func.count(ServiceEpisode.id)).where(ServiceEpisode.facility_id==facility.id,ServiceEpisode.service_point_id==point.id,ServiceEpisode.status.in_(["CALLED","IN_SERVICE","PAUSED"]))) or 0
        stages.append({"id":str(point.id),"name":point.name,"type":point.type,"waiting":len(ranked),"in_progress":occupied,"long_waits":sum(bool(e.get("long_wait_warning")) for e in ranked),"oldest_wait_minutes":max((e["waiting_minutes"] for e in ranked),default=0),"capacity":point.capacity,"availability":point.outage_state})
    todays=[v for v in visits if start<=v.arrival_at<end]
    counts={"arrivals_today":len(todays),"active_visits":len(active),"awaiting_triage":sum(v.status=="AWAITING_TRIAGE" for v in active),"completed_today":sum(v.completed_at is not None and start<=v.completed_at<end for v in visits),"escalations":sum(v.status=="ESCALATION_REQUIRED" for v in active),"waiting":sum(p["waiting"] for p in stages),"in_progress":sum(p["in_progress"] for p in stages),"long_waits":sum(p["long_waits"] for p in stages),"stored_visits":len(visits)}
    session=db.scalar(select(DemoSession).where(DemoSession.facility_id==facility.id).order_by(DemoSession.created_at.desc()))
    demo=None
    if session:
        demo={"session_id":str(session.id),"version":session.version,"prepared_at":session.anchor_at.isoformat(),"stale":(now-session.anchor_at).total_seconds()>8*3600,"fictional":True,"history_method":session.manifest_json["history_method"],"warning":session.manifest_json["warning"],"cases":[]}
        if roles&{"ADMIN","RECEPTIONIST","CLINICIAN","TRIAGE_NURSE"}:
            for case in session.manifest_json["cases"]:
                visit=db.get(Visit,UUID(case["visit_id"]))
                if visit and can_access_visit(user,visit):
                    demo["cases"].append({**case,"patient_label":visit.patient.pseudonym,"public_token":visit.public_token,"status":visit.status,"stage":visit.episodes[-1].service_point.name if visit.episodes else "Registration"})
        if roles&{"ADMIN","RESEARCHER","MANAGER"}:
            demo["jobs"]=[{"id":str(j.id),"type":j.type,"status":j.status,"result_ref":j.result_ref,"error":j.error_summary} for j in db.scalars(select(Job).where(Job.facility_id==facility.id).order_by(Job.created_at.desc()).limit(8))]
            demo["models"]=[{"version":m.version,"status":m.status,"active":m.active} for m in db.scalars(select(ModelVersion).where(ModelVersion.facility_id==facility.id))]
    return {"facility":{"name":facility.name,"timezone":facility.timezone,"research_mode":True},"generated_at":now,"day":day.isoformat(),"counts":counts,"services":stages,"hourly_arrivals":[{"hour":h,"arrivals":sum(v.arrival_at.astimezone(ZoneInfo(facility.timezone)).hour==h for v in todays)} for h in range(24)],"demonstration":demo}
