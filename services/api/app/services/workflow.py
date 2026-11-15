import secrets
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    QueueEntry,
    QueueStateEvent,
    ServiceEpisode,
    ServicePoint,
    Visit,
    Facility,
)
from app.security import token_digest


ACTIVE_VISIT_STATES = {
    "CREATED",
    "REGISTERING",
    "AWAITING_TRIAGE",
    "TRIAGED",
    "ACTIVE",
    "ESCALATION_REQUIRED",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_point(db: Session, facility_id: uuid.UUID, point_type: str) -> ServicePoint:
    point = db.scalar(
        select(ServicePoint).where(
            ServicePoint.facility_id == facility_id,
            ServicePoint.type == point_type,
            ServicePoint.active.is_(True),
        )
    )
    if not point:
        raise HTTPException(status_code=409, detail=f"Service point '{point_type}' is not configured")
    return point


def new_public_tokens(db: Session, facility_id: uuid.UUID) -> tuple[str, str, bytes]:
    facility = db.get(Facility, facility_id)
    today = now_utc().astimezone(ZoneInfo(facility.timezone)).date()
    count = db.scalar(
        select(func.count(Visit.id)).where(
            Visit.facility_id == facility_id,
            Visit.token_day == today,
        )
    ) or 0
    public_token = f"A-{count + 1:03d}"
    secret = secrets.token_urlsafe(24)
    opaque = f"{public_token}.{secret}"
    return public_token, opaque, token_digest(opaque)


def add_episode(
    db: Session,
    *,
    visit: Visit,
    point_type: str,
    actor_id: uuid.UUID,
    queued: bool = True,
) -> ServiceEpisode:
    db.flush()
    point = get_point(db, visit.facility_id, point_type)
    existing = db.scalar(
        select(ServiceEpisode).where(
            ServiceEpisode.visit_id == visit.id,
            ServiceEpisode.service_point_id == point.id,
            ServiceEpisode.status.in_(["PLANNED", "WAITING", "CALLED", "IN_SERVICE", "PAUSED"]),
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="An active episode already exists at this service point")
    sequence = (db.scalar(select(func.max(ServiceEpisode.sequence_no)).where(ServiceEpisode.visit_id == visit.id)) or 0) + 1
    timestamp = now_utc()
    episode = ServiceEpisode(
        facility_id=visit.facility_id,
        visit_id=visit.id,
        service_point_id=point.id,
        sequence_no=sequence,
        status="WAITING" if queued else "PLANNED",
        queued_at=timestamp if queued else None,
    )
    db.add(episode)
    db.flush()
    if queued:
        order = (
            db.scalar(
                select(func.max(QueueEntry.original_order)).where(
                    QueueEntry.facility_id == visit.facility_id,
                    QueueEntry.service_point_id == point.id,
                )
            )
            or 0
        ) + 1
        db.add(
            QueueEntry(
                facility_id=visit.facility_id,
                episode_id=episode.id,
                service_point_id=point.id,
                joined_at=timestamp,
                original_order=order,
            )
        )
        db.add(
            QueueStateEvent(
                facility_id=visit.facility_id,
                episode_id=episode.id,
                actor_id=actor_id,
                from_status="PLANNED",
                to_status="WAITING",
            )
        )
    return episode


def require_visit(db: Session, visit_id: uuid.UUID, facility_id: uuid.UUID) -> Visit:
    visit = db.scalar(select(Visit).where(Visit.id == visit_id, Visit.facility_id == facility_id))
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    return visit


def require_episode(db: Session, episode_id: uuid.UUID, facility_id: uuid.UUID) -> ServiceEpisode:
    episode = db.scalar(
        select(ServiceEpisode).where(
            ServiceEpisode.id == episode_id,
            ServiceEpisode.facility_id == facility_id,
        )
    )
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return episode


def transition_episode(
    db: Session,
    episode: ServiceEpisode,
    *,
    expected: set[str],
    target: str,
    actor_id: uuid.UUID,
    expected_version: int,
) -> None:
    if episode.status not in expected:
        raise HTTPException(status_code=409, detail=f"Cannot move {episode.status} to {target}")
    if episode.version != expected_version:
        raise HTTPException(status_code=409, detail="Episode has changed; refresh and try again")
    previous = episode.status
    timestamp = now_utc()
    episode.status = target
    episode.version += 1
    episode.clinician_id = actor_id
    if target == "IN_SERVICE":
        from app.resources import guard_reservation
        guard_reservation(db,episode,starting=True)
        point = episode.service_point
        if not point.active or point.capacity <= 0 or point.outage_state == "UNAVAILABLE":
            raise HTTPException(409, "Service point is unavailable")
        occupied = db.scalar(select(func.count(ServiceEpisode.id)).where(
            ServiceEpisode.service_point_id == point.id,
            ServiceEpisode.status.in_(["IN_SERVICE", "PAUSED"]), ServiceEpisode.id != episode.id)) or 0
        if occupied >= point.capacity:
            raise HTTPException(409, "All service capacity is occupied")
        active_elsewhere = db.scalar(
            select(ServiceEpisode.id).where(
                ServiceEpisode.visit_id == episode.visit_id,
                ServiceEpisode.status == "IN_SERVICE",
                ServiceEpisode.id != episode.id,
            )
        )
        if active_elsewhere:
            raise HTTPException(status_code=409, detail="Visit is already in service elsewhere")
        if not episode.called_at:
            episode.called_at = timestamp
        episode.started_at = episode.started_at or timestamp
        if episode.paused_at:
            start = episode.paused_at
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            episode.paused_seconds += max(0, (timestamp - start).total_seconds())
            episode.paused_at = None
    elif target == "COMPLETED":
        episode.ended_at = timestamp
    if target in {"COMPLETED", "CANCELLED", "NO_SHOW", "TRANSFERRED", "SKIPPED"}:
        from app.resources import release_assignment
        release_assignment(db,episode)
    if episode.queue_entry:
        episode.queue_entry.status = target
        episode.queue_entry.version += 1
        episode.queue_entry.manual_pin = False
        episode.queue_entry.pin_rank = None
    db.add(
        QueueStateEvent(
            facility_id=episode.facility_id,
            episode_id=episode.id,
            actor_id=actor_id,
            from_status=previous,
            to_status=target,
        )
    )

