import hashlib
import json
import uuid
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models import AuditEvent, EventOutbox


def safe_hash(value: Any) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def record_audit(
    db: Session,
    *,
    facility_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    object_type: str,
    object_id: uuid.UUID | str,
    correlation_id: str,
    old: Any = None,
    new: Any = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        facility_id=facility_id,
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        old_hash=safe_hash(old),
        new_hash=safe_hash(new),
        reason=reason,
        correlation_id=correlation_id,
        metadata_json=metadata or {},
    )
    db.add(event)
    return event


def enqueue_event(
    db: Session,
    *,
    facility_id: uuid.UUID,
    topic: str,
    aggregate_id: uuid.UUID | str,
    version: int = 1,
    payload: dict[str, Any] | None = None,
) -> EventOutbox:
    event = EventOutbox(
        facility_id=facility_id,
        topic=topic,
        aggregate_id=str(aggregate_id),
        aggregate_version=version,
        payload_json=jsonable_encoder(payload or {}),
    )
    db.add(event)
    return event

