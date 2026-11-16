"""Clinic-floor operations: day close, paper-downtime back-entry, waiting-room display
board and a system-health view (ADR-027 .. ADR-031).

Every mutation here follows the same contract as the rest of the API: facility-scoped,
role-checked, serialised by CommandRoute, idempotent and audited. Nothing here changes a
clinician-confirmed urgency or reorders a queue across urgency groups.
"""
import hashlib
import json
import secrets
import shutil
import time as clock
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.commands import CommandRoute
from app.config import settings
from app.database import get_db
from app.models import (
    DayClosure,
    DisplayScreen,
    EventOutbox,
    Facility,
    Job,
    Patient,
    QueueEntry,
    ResourceAssignment,
    Room,
    ServiceEpisode,
    ServicePoint,
    User,
    Visit,
    utcnow,
)
from app.schemas import APIModel
from app.security import client_key, rate_limiter, require_roles, token_digest
from app.services.audit import enqueue_event, record_audit
from app.services.queue import rank_queue
from app.services.workflow import ACTIVE_VISIT_STATES, transition_episode

router = APIRouter(prefix="/api/v1", route_class=CommandRoute)
DB = Depends(get_db, scope="function")

OPEN_EPISODE_STATES = {"PLANNED", "WAITING", "CALLED", "PAUSED", "IN_SERVICE"}
DAY_CLOSE_ROLES = ("ADMIN", "CLINICIAN")


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _zone(db: Session, facility_id: uuid.UUID) -> ZoneInfo:
    return ZoneInfo(db.get(Facility, facility_id).timezone)


# --------------------------------------------------------------------------- day close


class DayCloseRequest(APIModel):
    local_date: date
    reason: str = Field(min_length=5, max_length=240)
    # Visits an authorised person explicitly leaves open (for example, still being seen).
    keep_open: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    # Number of open visits shown in the preview; a mismatch means the floor changed.
    expected_open_count: int = Field(ge=0, le=5000)


def _open_items(db: Session, facility_id: uuid.UUID, through: date, zone: ZoneInfo) -> list[dict]:
    visits = db.scalars(
        select(Visit).where(Visit.facility_id == facility_id, Visit.status.in_(ACTIVE_VISIT_STATES)).order_by(Visit.arrival_at)
    ).all()
    items = []
    for visit in visits:
        arrival = _aware(visit.arrival_at)
        if arrival.astimezone(zone).date() > through:
            continue
        current = next((e for e in reversed(visit.episodes) if e.status in OPEN_EPISODE_STATES), None)
        started = bool(current and (current.status == "IN_SERVICE" or (current.status == "PAUSED" and current.started_at)))
        waiting_since = _aware(current.queued_at) if current and current.queued_at else arrival
        items.append({
            "visit_id": str(visit.id),
            "public_token": visit.public_token,
            "visit_status": visit.status,
            "stage": current.service_point.name if current else "Awaiting staff",
            "episode_status": current.status if current else None,
            "waiting_since": waiting_since,
            "arrived_on": arrival.astimezone(zone).date(),
            "blocking": started,
            "blocking_reason": "Service has started; complete it or record a hand-over first" if started else None,
        })
    return items


@router.get("/operations/day-close")
def day_close_preview(user: User = Depends(require_roles(*DAY_CLOSE_ROLES)), db: Session = DB, local_date: date | None = None):
    zone = _zone(db, user.facility_id)
    today = utcnow().astimezone(zone).date()
    target = local_date or today
    closure = db.scalar(select(DayClosure).where(DayClosure.facility_id == user.facility_id, DayClosure.local_date == target))
    items = _open_items(db, user.facility_id, target, zone)
    return {
        "local_date": target,
        "timezone": str(zone),
        "already_closed": closure is not None,
        "closure": None if not closure else {
            "closed_at": closure.closed_at, "reason": closure.reason, "summary": closure.summary_json,
            "closed_by": db.get(User, closure.closed_by).display_name,
        },
        "open_count": len(items),
        "blocking_count": sum(item["blocking"] for item in items),
        "items": items,
        "policy": "Unseen patients are recorded as left without service; history is preserved and nothing is deleted.",
    }


@router.post("/operations/day-close", status_code=201)
def close_day(payload: DayCloseRequest, user: User = Depends(require_roles(*DAY_CLOSE_ROLES)), db: Session = DB,
              key: str = Header(alias="Idempotency-Key")):
    zone = _zone(db, user.facility_id)
    today = utcnow().astimezone(zone).date()
    if payload.local_date > today or (today - payload.local_date).days > 7:
        raise HTTPException(422, "Close today or one of the previous seven days")
    if db.scalar(select(DayClosure.id).where(DayClosure.facility_id == user.facility_id, DayClosure.local_date == payload.local_date)):
        raise HTTPException(409, "This day has already been closed")
    items = _open_items(db, user.facility_id, payload.local_date, zone)
    if len(items) != payload.expected_open_count:
        raise HTTPException(409, "The queue changed since you reviewed it; refresh the day-close list")
    keep = {str(item) for item in payload.keep_open}
    unknown = keep - {item["visit_id"] for item in items}
    if unknown:
        raise HTTPException(422, "Kept visits must be open visits from the reviewed list")
    blocking = [item["public_token"] for item in items if item["blocking"] and item["visit_id"] not in keep]
    if blocking:
        raise HTTPException(409, f"Finish or explicitly keep open the visits already in service: {', '.join(blocking)}")
    closed, by_stage = 0, {}
    for item in items:
        if item["visit_id"] in keep:
            continue
        visit = db.get(Visit, uuid.UUID(item["visit_id"]))
        for episode in visit.episodes:
            if episode.status in {"PLANNED", "WAITING", "CALLED", "PAUSED"} and not episode.started_at:
                transition_episode(db, episode, expected={episode.status}, target="CANCELLED", actor_id=user.id,
                                   expected_version=episode.version)
        visit.status = "LEFT_WITHOUT_SERVICE"
        visit.version += 1
        closed += 1
        by_stage[item["stage"]] = by_stage.get(item["stage"], 0) + 1
        record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="visit.closed_at_day_end", object_type="Visit",
                     object_id=visit.id, correlation_id=key, old={"status": item["visit_status"]},
                     new={"status": "LEFT_WITHOUT_SERVICE"}, reason=payload.reason, metadata={"reason_code": "DAY_CLOSE_UNSEEN"})
        enqueue_event(db, facility_id=user.facility_id, topic="visit.state_changed", aggregate_id=visit.id, version=visit.version)
    summary = {"closed_unseen": closed, "kept_open": len(keep), "closed_by_stage": by_stage, "reviewed_open": len(items)}
    closure = DayClosure(facility_id=user.facility_id, local_date=payload.local_date, closed_by=user.id, reason=payload.reason,
                         summary_json=summary)
    db.add(closure)
    db.flush()
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="day.closed", object_type="DayClosure",
                 object_id=closure.id, correlation_id=key, new=summary, reason=payload.reason)
    return jsonable_encoder({"id": str(closure.id), "local_date": payload.local_date, **summary})


# ------------------------------------------------------------ paper downtime back-entry


class RetroStage(APIModel):
    service_type: Literal["registration", "triage", "consultation", "pharmacy", "laboratory", "discharge"]
    queued_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @model_validator(mode="after")
    def ordered(self):
        for value in (self.queued_at, self.started_at, self.ended_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("Times must include a timezone")
        if self.ended_at and not self.started_at:
            raise ValueError("An end time needs a start time")
        if self.started_at and self.started_at < self.queued_at:
            raise ValueError("Service cannot start before the patient queued")
        if self.ended_at and self.started_at and self.ended_at < self.started_at:
            raise ValueError("Service cannot end before it started")
        return self


class RetrospectiveVisit(APIModel):
    patient_id: uuid.UUID
    visit_type: Literal["walk_in", "scheduled", "referral", "follow_up"] = "walk_in"
    arrival_at: datetime
    paper_reference: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9 #/._:-]+$")
    reason: str = Field(min_length=5, max_length=240)
    outcome: Literal["COMPLETED", "LEFT_WITHOUT_SERVICE"]
    stages: list[RetroStage] = Field(min_length=1, max_length=8)

    @field_validator("arrival_at")
    @classmethod
    def aware(cls, value: datetime):
        if value.tzinfo is None:
            raise ValueError("Arrival must include a timezone")
        return value


@router.post("/operations/retrospective-visits", status_code=201)
def record_retrospective_visit(payload: RetrospectiveVisit, user: User = Depends(require_roles("ADMIN", "RECEPTIONIST")),
                               db: Session = DB, key: str = Header(alias="Idempotency-Key")):
    now = utcnow()
    if payload.arrival_at > now or (now - payload.arrival_at).days > 7:
        raise HTTPException(422, "Back-entry covers paper records from the last seven days")
    patient = db.scalar(select(Patient).where(Patient.id == payload.patient_id, Patient.facility_id == user.facility_id))
    if not patient:
        raise HTTPException(404, "Patient not found")
    previous_end = payload.arrival_at
    for index, stage in enumerate(payload.stages):
        last = index == len(payload.stages) - 1
        if stage.queued_at < previous_end:
            raise HTTPException(422, f"Stage {index + 1} starts before the previous step ended")
        if any(value and value > now for value in (stage.queued_at, stage.started_at, stage.ended_at)):
            raise HTTPException(422, "Paper times cannot be in the future")
        if not stage.ended_at and not (last and payload.outcome == "LEFT_WITHOUT_SERVICE"):
            raise HTTPException(422, "Every stage except an unfinished final stage needs start and end times")
        previous_end = stage.ended_at or stage.queued_at
    points = {p.type: p for p in db.scalars(select(ServicePoint).where(ServicePoint.facility_id == user.facility_id))}
    missing = {stage.service_type for stage in payload.stages} - set(points)
    if missing:
        raise HTTPException(422, f"Service points not configured: {', '.join(sorted(missing))}")
    zone = _zone(db, user.facility_id)
    day = payload.arrival_at.astimezone(zone).date()
    count = db.scalar(select(func.count(Visit.id)).where(Visit.facility_id == user.facility_id, Visit.token_day == day,
                                                          Visit.public_token.like("P-%"))) or 0
    final = payload.stages[-1]
    visit = Visit(
        facility_id=user.facility_id, patient_id=patient.id, public_token=f"P-{count + 1:03d}", token_day=day,
        # No status lookup exists for a back-entered visit; the digest is random and unused.
        token_secret_hash=token_digest(secrets.token_urlsafe(32)), arrival_at=payload.arrival_at,
        registered_at=next((s.ended_at for s in payload.stages if s.service_type == "registration"), None),
        completed_at=final.ended_at if payload.outcome == "COMPLETED" else None, status=payload.outcome,
        visit_type=payload.visit_type, planned_services=[s.service_type for s in payload.stages],
        entry_mode="RETROSPECTIVE", paper_reference=payload.paper_reference,
    )
    db.add(visit)
    db.flush()
    for index, stage in enumerate(payload.stages, start=1):
        finished = stage.ended_at is not None
        db.add(ServiceEpisode(
            facility_id=user.facility_id, visit_id=visit.id, service_point_id=points[stage.service_type].id, sequence_no=index,
            status="COMPLETED" if finished else "CANCELLED", queued_at=stage.queued_at,
            called_at=stage.started_at, started_at=stage.started_at, ended_at=stage.ended_at, clinician_id=None,
        ))
    db.flush()
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="visit.retrospective_recorded", object_type="Visit",
                 object_id=visit.id, correlation_id=key, new={"outcome": payload.outcome, "stages": len(payload.stages)},
                 reason=payload.reason, metadata={"entry_mode": "RETROSPECTIVE",
                                                  "paper_reference_hash": hashlib.sha256(payload.paper_reference.encode()).hexdigest()})
    enqueue_event(db, facility_id=user.facility_id, topic="visit.created", aggregate_id=visit.id)
    return jsonable_encoder({"id": str(visit.id), "public_token": visit.public_token, "status": visit.status,
                             "entry_mode": "RETROSPECTIVE", "stages": len(payload.stages)})


# --------------------------------------------------------------- waiting-room display


class DisplayCreate(APIModel):
    label: str = Field(min_length=2, max_length=80)


class DisplayBoardRequest(APIModel):
    key: str = Field(min_length=20, max_length=120)


def _display_view(screen: DisplayScreen) -> dict:
    return {"id": str(screen.id), "label": screen.label, "created_at": screen.created_at,
            "revoked_at": screen.revoked_at, "last_seen_at": screen.last_seen_at, "active": screen.revoked_at is None}


@router.get("/admin/display-screens")
def list_display_screens(user: User = Depends(require_roles("ADMIN")), db: Session = DB):
    screens = db.scalars(select(DisplayScreen).where(DisplayScreen.facility_id == user.facility_id)
                         .order_by(DisplayScreen.created_at.desc())).all()
    return [_display_view(item) for item in screens]


@router.post("/admin/display-screens", status_code=201)
def create_display_screen(payload: DisplayCreate, user: User = Depends(require_roles("ADMIN")), db: Session = DB,
                          key: str = Header(alias="Idempotency-Key")):
    secret = "dsp_" + secrets.token_urlsafe(32)
    screen = DisplayScreen(facility_id=user.facility_id, label=payload.label, secret_hash=token_digest(secret), created_by=user.id)
    db.add(screen)
    db.flush()
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="display.created", object_type="DisplayScreen",
                 object_id=screen.id, correlation_id=key, new={"label": payload.label})
    # The key is shown once. CommandRoute strips `display_key` before storing the replay.
    return jsonable_encoder({**_display_view(screen), "display_key": secret})


@router.post("/admin/display-screens/{screen_id}/revoke")
def revoke_display_screen(screen_id: uuid.UUID, user: User = Depends(require_roles("ADMIN")), db: Session = DB,
                          key: str = Header(alias="Idempotency-Key")):
    screen = db.scalar(select(DisplayScreen).where(DisplayScreen.id == screen_id, DisplayScreen.facility_id == user.facility_id))
    if not screen:
        raise HTTPException(404, "Display not found")
    if screen.revoked_at is None:
        screen.revoked_at = utcnow()
        record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="display.revoked", object_type="DisplayScreen",
                     object_id=screen.id, correlation_id=key, new={"revoked": True})
    return jsonable_encoder(_display_view(screen))


@router.post("/display/board")
def display_board(payload: DisplayBoardRequest, request: Request, db: Session = DB):
    """Public, credential-scoped board: display numbers being called and queue lengths only.

    No pseudonyms, urgency, order of waiting patients or reasons are ever returned, so the
    board cannot be used to infer who was prioritised.
    """
    miss_key = client_key(request, "display-miss")
    rate_limiter.guard(miss_key, 20, 60)
    rate_limiter.check(client_key(request, "display-ip"), 120, 60)
    screen = db.scalar(select(DisplayScreen).where(DisplayScreen.secret_hash == token_digest(payload.key),
                                                   DisplayScreen.revoked_at.is_(None)))
    if not screen:
        rate_limiter.record(miss_key)
        raise HTTPException(404, "Display key is not valid or was revoked")
    now = utcnow()
    if screen.last_seen_at is None or (now - _aware(screen.last_seen_at)).total_seconds() > 60:
        screen.last_seen_at = now
        db.commit()
    facility = db.get(Facility, screen.facility_id)
    zone = ZoneInfo(facility.timezone)
    called = db.scalars(select(ServiceEpisode).where(ServiceEpisode.facility_id == screen.facility_id,
                                                     ServiceEpisode.status == "CALLED")).all()
    rooms = {}
    if called:
        rows = db.execute(select(ResourceAssignment.episode_id, Room.name).join(Room, Room.id == ResourceAssignment.room_id)
                          .where(ResourceAssignment.episode_id.in_([e.id for e in called]),
                                 ResourceAssignment.released_at.is_(None))).all()
        rooms = {episode_id: name for episode_id, name in rows}
    now_calling = []
    for episode in called:
        entry = episode.queue_entry
        announced = max(filter(None, [_aware(episode.called_at), _aware(entry.last_recalled_at) if entry else None]), default=now)
        now_calling.append({"token": episode.visit.public_token, "service": episode.service_point.name,
                            "service_type": episode.service_point.type, "room": rooms.get(episode.id),
                            "announced_at": announced, "recall_count": entry.recall_count if entry else 0})
    now_calling.sort(key=lambda item: item["announced_at"], reverse=True)
    points = db.scalars(select(ServicePoint).where(ServicePoint.facility_id == screen.facility_id, ServicePoint.active.is_(True))
                        .order_by(ServicePoint.name)).all()
    queues = []
    for point in points:
        if point.type in {"registration", "discharge"}:
            continue
        waiting = len(rank_queue(db, screen.facility_id, point.id))
        queues.append({"service": point.name, "service_type": point.type, "waiting": waiting,
                       "open": point.capacity > 0 and point.outage_state != "UNAVAILABLE"})
    return {"facility": facility.name, "label": screen.label, "now_calling": now_calling[:12], "queues": queues,
            "generated_at": now, "local_time": now.astimezone(zone).strftime("%H:%M"),
            "research_notice": "Research prototype — synthetic demonstration data"}


# ---------------------------------------------------------------------- system health


def _read_backup_status() -> dict:
    path = settings.backup_status_path
    if not path:
        return {"state": "unknown", "detail": "Backup status is not mounted into the API (BACKUP_STATUS_PATH)."}
    try:
        data = json.loads(path.read_text())
        completed = datetime.fromisoformat(data["completed_at"])
        age_hours = (utcnow() - _aware(completed)).total_seconds() / 3600
        encrypted = bool(data.get("encrypted"))
        detail = None
        if age_hours > 26:
            detail = "The last backup is more than a day old."
        elif not encrypted:
            detail = "The last backup was not encrypted (set BACKUP_PASSPHRASE_FILE)."
        return {"state": "ok" if detail is None else "attention", "completed_at": completed, "age_hours": round(age_hours, 1),
                "encrypted": encrypted, "snapshot": data.get("snapshot"), "detail": detail}
    except FileNotFoundError:
        return {"state": "attention", "detail": "No backup has been recorded yet."}
    except (ValueError, KeyError, OSError):
        return {"state": "attention", "detail": "Backup status file could not be read."}


@router.get("/admin/system-health")
def system_health(user: User = Depends(require_roles("ADMIN", "MANAGER")), db: Session = DB):
    started = clock.perf_counter()
    db.execute(select(1))
    latency_ms = round((clock.perf_counter() - started) * 1000, 1)
    revision = None
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # SQLite tests and pre-migration databases have no alembic table.
        db.rollback()
    now = utcnow()
    zone = _zone(db, user.facility_id)
    today = now.astimezone(zone).date()
    jobs = {status: count for status, count in db.execute(
        select(Job.status, func.count(Job.id)).where(Job.facility_id == user.facility_id).group_by(Job.status)).all()}
    oldest_pending = db.scalar(select(func.min(Job.created_at)).where(Job.facility_id == user.facility_id, Job.status == "PENDING"))
    stale_running = db.scalar(select(func.count(Job.id)).where(Job.facility_id == user.facility_id, Job.status == "RUNNING",
                                                               Job.updated_at < now - timedelta(minutes=15))) or 0
    pending_age = round((now - _aware(oldest_pending)).total_seconds() / 60) if oldest_pending else None
    events_hour = db.scalar(select(func.count(EventOutbox.id)).where(EventOutbox.facility_id == user.facility_id,
                                                                     EventOutbox.created_at >= now - timedelta(hours=1))) or 0
    try:
        usage = shutil.disk_usage(settings.model_artifact_dir)
        free_percent = round(usage.free / usage.total * 100, 1)
        storage = {"state": "ok" if free_percent >= 10 else "attention", "free_bytes": usage.free, "total_bytes": usage.total,
                   "free_percent": free_percent}
    except OSError:
        storage = {"state": "unknown"}
    locked = db.scalar(select(func.count(User.id)).where(User.facility_id == user.facility_id, User.locked_until > now)) or 0
    temporary = db.scalar(select(func.count(User.id)).where(User.facility_id == user.facility_id,
                                                            User.must_change_password.is_(True), User.active.is_(True))) or 0
    displays = db.scalars(select(DisplayScreen).where(DisplayScreen.facility_id == user.facility_id,
                                                      DisplayScreen.revoked_at.is_(None))).all()
    carried = 0
    for entry in db.scalars(select(QueueEntry).where(QueueEntry.facility_id == user.facility_id, QueueEntry.status == "WAITING")):
        if _aware(entry.joined_at).astimezone(zone).date() < today:
            carried += 1
    open_visits = db.scalar(select(func.count(Visit.id)).where(Visit.facility_id == user.facility_id,
                                                               Visit.status.in_(ACTIVE_VISIT_STATES))) or 0
    yesterday_closed = db.scalar(select(DayClosure.id).where(DayClosure.facility_id == user.facility_id,
                                                             DayClosure.local_date == today - timedelta(days=1))) is not None
    worker_state = "attention" if stale_running or (pending_age is not None and pending_age > 10) else "ok"
    backup = _read_backup_status()
    checks = {
        "database": {"state": "ok", "latency_ms": latency_ms, "migration": revision},
        "worker": {"state": worker_state, "jobs": jobs, "stale_running": stale_running, "oldest_pending_minutes": pending_age},
        "live_updates": {"state": "ok", "events_last_hour": events_hour},
        "storage": storage,
        "backup": backup,
        "security": {"state": "attention" if locked or not settings.cookie_secure else "ok", "locked_accounts": locked,
                     "temporary_passwords": temporary, "secure_cookies": settings.cookie_secure,
                     "session_idle_minutes": settings.session_idle_minutes, "session_absolute_minutes": settings.session_minutes},
        "operations": {"state": "attention" if carried else "ok", "open_visits": open_visits, "carried_over_waiting": carried,
                       "previous_day_closed": yesterday_closed},
        "displays": {"state": "ok", "active": len(displays),
                     "stale": sum(1 for d in displays if not d.last_seen_at or (now - _aware(d.last_seen_at)).total_seconds() > 300)},
    }
    overall = "ok" if all(item.get("state") in {"ok", "unknown"} for item in checks.values()) else "attention"
    return jsonable_encoder({"status": overall, "server_time": now, "timezone": str(zone), "research_mode": settings.research_mode,
                             "checks": checks})
