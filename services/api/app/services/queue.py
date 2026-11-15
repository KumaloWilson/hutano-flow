import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import QueueEntry, ServiceEpisode, ServicePoint, TriageAssessment, Visit, QueuePolicy


URGENCY_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}
ELIGIBLE = {"WAITING"}


@dataclass
class RankedEntry:
    queue_entry_id: str
    episode_id: str
    visit_id: str
    public_token: str
    status: str
    confirmed_urgency: str | None
    recommended_order: int
    waiting_minutes: int
    long_wait_warning: bool
    manual_pin: bool
    version: int
    policy_version: str
    explanations: list[str]
    score_components: dict[str, float]
    requires_clinician_review: bool = False
    model_suggestion_applied_automatically: bool = False
    deferred_until: datetime | None = None
    missed_calls: int = 0
    carried_over: bool = False

    def dict(self) -> dict:
        return asdict(self)


def latest_urgency(db: Session, visit_id: uuid.UUID) -> str | None:
    return db.scalar(
        select(TriageAssessment.configured_urgency)
        .where(TriageAssessment.visit_id == visit_id)
        .order_by(TriageAssessment.assessed_at.desc())
        .limit(1)
    )


def rank_queue(db: Session, facility_id: uuid.UUID, service_point_id: uuid.UUID) -> list[dict]:
    point = db.scalar(
        select(ServicePoint).where(
            ServicePoint.id == service_point_id, ServicePoint.facility_id == facility_id
        )
    )
    if not point:
        raise HTTPException(status_code=404, detail="Service point not found")
    policy = db.scalar(select(QueuePolicy).where(QueuePolicy.facility_id == facility_id, QueuePolicy.active.is_(True)))
    config = policy.config_json if policy else {}
    mode = config.get("mode", "HYBRID")
    warning_minutes = config.get("long_wait_warning_minutes", 60)
    entries = db.scalars(
        select(QueueEntry)
        .join(QueueEntry.episode)
        .where(
            QueueEntry.facility_id == facility_id,
            QueueEntry.service_point_id == service_point_id,
            QueueEntry.status.in_(ELIGIBLE),
            ServiceEpisode.status == "WAITING",
        )
    ).all()
    now = datetime.now(timezone.utc)
    from zoneinfo import ZoneInfo
    from app.models import Facility
    facility = db.get(Facility, facility_id)
    zone = ZoneInfo(facility.timezone if facility else "UTC")
    today = now.astimezone(zone).date()
    scored: list[tuple] = []
    for entry in entries:
        visit = entry.episode.visit
        if visit.status == "ESCALATION_REQUIRED":
            continue
        urgency = latest_urgency(db, visit.id)
        # Registration/triage can be operationally queued before urgency exists; consultation cannot.
        if point.type == "consultation" and urgency is None:
            continue
        joined = entry.joined_at
        if joined.tzinfo is None:
            joined = joined.replace(tzinfo=timezone.utc)
        age = max(0, int((now - joined).total_seconds() // 60))
        # Ageing is deliberately bounded inside the clinician-confirmed urgency group.
        age_score = min(age, 240) / 240
        manual_bucket = 0 if entry.manual_pin else 1
        pin_rank = entry.pin_rank if entry.manual_pin and entry.pin_rank is not None else 9999
        deferred = entry.deferred_until
        if deferred is not None and deferred.tzinfo is None:
            deferred = deferred.replace(tzinfo=timezone.utc)
        # A patient who missed a call keeps their place but is only routinely callable
        # once the grace period ends; until then they rank after everyone callable.
        deferred_bucket = 1 if deferred is not None and deferred > now else 0
        scored.append(
            (
                manual_bucket,
                pin_rank,
                deferred_bucket,
                0 if mode == "FCFS" or point.type in {"registration", "triage"} else URGENCY_ORDER.get(urgency, 99),
                -age_score * config.get("waiting_weight", 0.25) if mode == "HYBRID" else 0,
                entry.joined_at,
                str(entry.id),
                entry,
                urgency,
                age,
                deferred if deferred_bucket else None,
                joined.astimezone(zone).date() < today,
            )
        )
    # First rank the unpinned entries. Insert clinician pins at their requested positions.
    ordinary = sorted([item for item in scored if not item[7].manual_pin], key=lambda item: item[2:7])
    pins = sorted([item for item in scored if item[7].manual_pin], key=lambda item: (item[1], item[6]))
    for item in pins:
        ordinary.insert(min(item[1] - 1, len(ordinary)), item)
    scored = ordinary
    result: list[dict] = []
    for index, item in enumerate(scored, start=1):
        entry, urgency, age, deferred_until, carried_over = item[7], item[8], item[9], item[10], item[11]
        confirmed = latest_urgency(db, entry.episode.visit_id)
        explanations = [f"Clinician-confirmed priority {urgency}" if confirmed else "Awaiting clinician assessment; arrival-order queue", f"Waiting {age} minutes"]
        if entry.manual_pin:
            explanations.insert(0, "Clinician override is active")
        if deferred_until:
            explanations.insert(0, f"Missed call; place kept, callable from {deferred_until.astimezone(zone):%H:%M}")
        if carried_over:
            explanations.insert(0, "Joined on an earlier day; review at day close")
        if point.capacity == 0 or point.outage_state == "UNAVAILABLE":
            explanations.append("Service point unavailable; queue is paused")
        components = {
            "urgency_component": (6 - URGENCY_ORDER.get(urgency, 6)) * float(config.get("urgency_weight", 1)),
            "waiting_age_component": min(age, 240) / 240 * float(config.get("waiting_weight", .25)),
            "service_availability_component": float(point.capacity > 0 and point.outage_state != "UNAVAILABLE") * float(config.get("capacity_weight", 0)),
        }
        explanations.append(f"{mode} policy; ageing cannot cross clinician-confirmed categories; capacity {point.capacity}")
        result.append(
            RankedEntry(
                queue_entry_id=str(entry.id),
                episode_id=str(entry.episode_id),
                visit_id=str(entry.episode.visit_id),
                public_token=entry.episode.visit.public_token,
                status=entry.status,
                confirmed_urgency=urgency,
                recommended_order=index,
                waiting_minutes=age,
                long_wait_warning=age >= warning_minutes,
                manual_pin=entry.manual_pin,
                version=entry.version,
                policy_version=policy.version if policy else entry.policy_version,
                explanations=explanations,
                score_components=components,
                deferred_until=deferred_until,
                missed_calls=entry.missed_calls or 0,
                carried_over=carried_over,
            ).dict()
        )
    return result


def atomic_call(db: Session, entry: QueueEntry, actor_id: uuid.UUID, expected_version: int) -> None:
    from app.resources import guard_reservation
    guard_reservation(db,entry.episode)
    point = db.scalar(select(ServicePoint).where(ServicePoint.id == entry.service_point_id))
    if not point or point.capacity <= 0 or point.outage_state == "UNAVAILABLE":
        raise HTTPException(status_code=409, detail="Service point is unavailable")
    occupied = db.scalar(select(func.count(ServiceEpisode.id)).where(ServiceEpisode.service_point_id == point.id,
        ServiceEpisode.status.in_(["CALLED", "IN_SERVICE", "PAUSED"]))) or 0
    if occupied >= point.capacity:
        raise HTTPException(409, "All service capacity is already reserved")
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(QueueEntry)
        .where(
            QueueEntry.id == entry.id,
            QueueEntry.status == "WAITING",
            QueueEntry.version == expected_version,
        )
        .values(status="CALLED", manual_pin=False, pin_rank=None, deferred_until=None, recall_count=0,
                version=QueueEntry.version + 1, updated_at=now)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Queue entry has changed; refresh before calling")
    episode_result = db.execute(
        update(ServiceEpisode)
        .where(ServiceEpisode.id == entry.episode_id, ServiceEpisode.status == "WAITING")
        .values(status="CALLED", called_at=now, clinician_id=actor_id, version=ServiceEpisode.version + 1)
    )
    if episode_result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Episode is no longer waiting")

