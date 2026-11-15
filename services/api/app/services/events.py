"""Role-scoped invalidations only: clients refetch through authorised REST routes."""
import uuid
from app.access import allowed_services, OPERATIONAL_ROLES
from app.models import QueueEntry, QueuePolicy, ServiceEpisode, ServicePoint, Visit
from app.security import role_names

RESEARCH_TOPICS = {"simulation.completed", "model.training_completed", "model.registry_changed"}


def visible_event(db, user, event):
    if event.facility_id != user.facility_id:
        return False
    roles = role_names(user)
    if not roles & OPERATIONAL_ROLES:
        if 'MANAGER' in roles and event.topic=='service_point.capacity_changed':
            return True
        return bool(roles & {"MANAGER", "RESEARCHER"}) and event.topic in RESEARCH_TOPICS
    if roles & {"ADMIN", "RECEPTIONIST", "CLINICIAN", "TRIAGE_NURSE"}:
        return event.topic != "model.recommendation_ready" or bool(roles & {"CLINICIAN", "TRIAGE_NURSE"})
    try:
        ref = uuid.UUID(event.aggregate_id)
    except ValueError:
        return False
    services = allowed_services(user)
    episode = db.get(ServiceEpisode, ref)
    if not episode:
        entry = db.get(QueueEntry, ref)
        episode = entry.episode if entry else None
    if episode:
        return episode.facility_id == user.facility_id and episode.service_point.type in services
    point = db.get(ServicePoint, ref)
    if point:
        return point.facility_id == user.facility_id and point.type in services
    visit = db.get(Visit, ref)
    if visit:
        return visit.facility_id == user.facility_id and any(ep.service_point.type in services for ep in visit.episodes)
    policy = db.get(QueuePolicy, ref)
    return bool(policy and policy.facility_id == user.facility_id and event.topic == "queue.rank_changed")


def invalidation(event):
    # Never forward arbitrary stored payloads, pseudonyms, observations, or reasons.
    return {"event_id": str(event.id), "topic": event.topic,
            "aggregate_id": event.aggregate_id, "aggregate_version": event.aggregate_version,
            "occurred_at": event.created_at.isoformat(), "data": {}}
