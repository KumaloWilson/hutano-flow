import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.types import UTCDateTime
from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuidpk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Facility(Base, TimestampMixin):
    __tablename__ = "facilities"
    id = uuidpk()
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Harare")
    demo_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=365)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    roles: Mapped[list["UserRole"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class UserRole(Base):
    __tablename__ = "user_roles"
    id = uuidpk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("user_id", "facility_id", "role"),)


class DemoSession(Base):
    __tablename__ = "demo_sessions"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    version: Mapped[str] = mapped_column(String(60))
    anchor_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True))
    seed: Mapped[int] = mapped_column(Integer)
    manifest_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)


class Patient(Base, TimestampMixin):
    __tablename__ = "patients"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    pseudonym: Mapped[str | None] = mapped_column(String(120), nullable=True)
    year_of_birth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_band: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sex: Mapped[str | None] = mapped_column(String(30), nullable=True)
    synthetic_flag: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("year_of_birth IS NULL OR year_of_birth BETWEEN 1900 AND 2200"),)


class Visit(Base, TimestampMixin):
    __tablename__ = "visits"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    public_token: Mapped[str] = mapped_column(String(24))
    token_day = mapped_column(Date, nullable=False, default=lambda: utcnow().date())
    token_secret_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    arrival_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    registered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="REGISTERING", index=True)
    visit_type: Mapped[str] = mapped_column(String(40), default="walk_in")
    planned_services: Mapped[list[str]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    patient: Mapped[Patient] = relationship(lazy="joined")
    episodes: Mapped[list["ServiceEpisode"]] = relationship(
        back_populates="visit", order_by="ServiceEpisode.sequence_no", lazy="selectin"
    )
    __table_args__ = (
        UniqueConstraint("facility_id", "public_token", "token_day", name="uq_public_token_day"),
        Index("ix_visits_facility_arrival", "facility_id", "arrival_at"),
        Index("uq_patient_active_visit", "patient_id", unique=True,
              postgresql_where=text("status IN ('CREATED','REGISTERING','AWAITING_TRIAGE','TRIAGED','ACTIVE','ESCALATION_REQUIRED')"),
              sqlite_where=text("status IN ('CREATED','REGISTERING','AWAITING_TRIAGE','TRIAGED','ACTIVE','ESCALATION_REQUIRED')")),
    )


class ServicePoint(Base, TimestampMixin):
    __tablename__ = "service_points"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(40))
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    outage_state: Mapped[str] = mapped_column(String(40), default="AVAILABLE")
    outage_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    operating_hours: Mapped[dict] = mapped_column(JSON, default=lambda: {"open": "08:00", "close": "17:00"})
    allowed_routes: Mapped[list] = mapped_column(JSON, default=lambda: ["consultation", "pharmacy", "laboratory", "discharge"])
    __table_args__ = (UniqueConstraint("facility_id", "type"), CheckConstraint("capacity >= 0"))


class ServiceEpisode(Base, TimestampMixin):
    __tablename__ = "service_episodes"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), index=True)
    service_point_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_points.id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="PLANNED", index=True)
    queued_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    called_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    clinician_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    operational_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    paused_seconds: Mapped[float] = mapped_column(Float, default=0)
    visit: Mapped[Visit] = relationship(back_populates="episodes")
    service_point: Mapped[ServicePoint] = relationship(lazy="joined")
    queue_entry: Mapped["QueueEntry | None"] = relationship(back_populates="episode", uselist=False, lazy="selectin")
    corrections: Mapped[list["EpisodeCorrection"]] = relationship(order_by="EpisodeCorrection.created_at", lazy="selectin")
    __table_args__ = (
        UniqueConstraint("visit_id", "sequence_no"),
        Index("ix_episodes_service_status", "service_point_id", "status"),
        CheckConstraint("started_at IS NULL OR called_at IS NULL OR started_at >= called_at"),
        CheckConstraint("called_at IS NULL OR queued_at IS NULL OR called_at >= queued_at"),
        CheckConstraint("ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at"),
        Index("uq_visit_in_service", "visit_id", unique=True,
              postgresql_where=text("status = 'IN_SERVICE'"), sqlite_where=text("status = 'IN_SERVICE'")),
        Index("uq_visit_point_active", "visit_id", "service_point_id", unique=True,
              postgresql_where=text("status IN ('PLANNED','WAITING','CALLED','IN_SERVICE','PAUSED')"),
              sqlite_where=text("status IN ('PLANNED','WAITING','CALLED','IN_SERVICE','PAUSED')")),
    )


class QueueEntry(Base, TimestampMixin):
    __tablename__ = "queue_entries"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_episodes.id"), unique=True)
    service_point_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_points.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="WAITING", index=True)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    manual_pin: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pin_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_order: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[str] = mapped_column(String(80), default="demo-hybrid-v1")
    version: Mapped[int] = mapped_column(Integer, default=1)
    episode: Mapped[ServiceEpisode] = relationship(back_populates="queue_entry", lazy="joined")
    __table_args__ = (
        Index("ix_queue_facility_status_joined", "facility_id", "status", "joined_at"),
        CheckConstraint("pin_rank IS NULL OR pin_rank > 0"),
    )


class TriageAssessment(Base, TimestampMixin):
    __tablename__ = "triage_assessments"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), index=True)
    assessor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    configured_urgency: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    assessed_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Observation(Base, TimestampMixin):
    __tablename__ = "observations"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), index=True)
    field_code: Mapped[str] = mapped_column(String(80))
    value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(40), default="CLINICIAN_ENTERED")
    entered_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PriorityRecommendation(Base, TimestampMixin):
    __tablename__ = "priority_recommendations"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), index=True)
    queue_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("queue_entries.id"), nullable=True)
    algorithm_type: Mapped[str] = mapped_column(String(50), default="QUEUE_POLICY")
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(80), default="demo-hybrid-v1")
    suggestion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requires_clinician_review: Mapped[bool] = mapped_column(Boolean, default=True)


class ClinicianDecision(Base, TimestampMixin):
    __tablename__ = "clinician_decisions"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("priority_recommendations.id"), nullable=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), index=True)
    clinician_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(30))
    final_urgency: Mapped[str] = mapped_column(String(10))
    justification: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)


class QueuePolicy(Base, TimestampMixin):
    __tablename__ = "queue_policies"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="Hybrid research policy")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[str] = mapped_column(String(80))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("facility_id", "version"),)


class QueueStateEvent(Base):
    __tablename__ = "queue_state_events"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_episodes.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_facility_occurred", "facility_id", "occurred_at"),)
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    object_type: Mapped[str] = mapped_column(String(80))
    object_id: Mapped[str] = mapped_column(String(80))
    old_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow, index=True)
    correlation_id: Mapped[str] = mapped_column(String(100), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EventOutbox(Base):
    __tablename__ = "event_outbox"
    __table_args__ = (Index("ix_outbox_facility_created", "facility_id", "created_at"),)
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    topic: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[str] = mapped_column(String(80))
    aggregate_version: Mapped[int] = mapped_column(Integer, default=1)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow, index=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(180))
    key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("actor_id", "endpoint", "key"),)


class Dataset(Base, TimestampMixin):
    __tablename__ = "datasets"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(40))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    consent_basis_note: Mapped[str] = mapped_column(String(500))
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    row_count: Mapped[int] = mapped_column(Integer)
    synthetic_flag: Mapped[bool] = mapped_column(Boolean, default=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    __table_args__ = (UniqueConstraint("facility_id", "dataset_hash"),)


class ModelVersion(Base, TimestampMixin):
    __tablename__ = "model_versions"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    model_name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(80))
    artifact_path: Mapped[str] = mapped_column(String(500))
    feature_schema_hash: Mapped[str] = mapped_column(String(64))
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"))
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="EXPERIMENTAL")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    __table_args__ = (UniqueConstraint("facility_id", "model_name", "version"),)


class SimulationScenario(Base, TimestampMixin):
    __tablename__ = "simulation_scenarios"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    scenario_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    synthetic_flag: Mapped[bool] = mapped_column(Boolean, default=True)


class SimulationRun(Base, TimestampMixin):
    __tablename__ = "simulation_runs"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    scenario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("simulation_scenarios.id"), index=True)
    policy: Mapped[str] = mapped_column(String(40))
    seed: Mapped[int] = mapped_column(Integer)
    replications: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    results_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    __table_args__ = (Index("ix_sim_scenario_policy_seed", "scenario_id", "policy", "seed"),)


class ResearchFeedback(Base, TimestampMixin):
    __tablename__ = "research_feedback"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    role_group: Mapped[str] = mapped_column(String(60))
    task_id: Mapped[str] = mapped_column(String(80))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    consent_ref: Mapped[str] = mapped_column(String(100))


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_pending_created", "status", "created_at"),)
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    result_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)


class EpisodeCorrection(Base):
    __tablename__ = "episode_corrections"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_episodes.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    original_values: Mapped[dict] = mapped_column(JSON)
    corrected_values: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)


class EncounterNote(Base):
    __tablename__ = "encounter_notes"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_episodes.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)


class Handover(Base, TimestampMixin):
    __tablename__ = "handovers"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), index=True)
    source_episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_episodes.id"))
    target_point_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_points.id"))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(String(1000))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Room(Base, TimestampMixin):
    __tablename__ = "rooms"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    service_point_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_points.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("facility_id", "name"),)


class StaffShift(Base, TimestampMixin):
    __tablename__ = "staff_shifts"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("ends_at > starts_at"),)


class ResourceBlock(Base, TimestampMixin):
    __tablename__ = "resource_blocks"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    room_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rooms.id"), nullable=True, index=True)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(240))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("ends_at > starts_at"), CheckConstraint("(room_id IS NULL) <> (staff_id IS NULL)"))


class ResourceAssignment(Base):
    __tablename__ = "resource_assignments"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_episodes.id"), index=True)
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    prediction_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = tuple(Index(f"uq_assignment_active_{column}", column, unique=True,
        postgresql_where=text("released_at IS NULL"), sqlite_where=text("released_at IS NULL"))
        for column in ["episode_id", "room_id", "staff_id"])


class RoutingProposal(Base, TimestampMixin):
    __tablename__ = "routing_proposals"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_episodes.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    queue_version: Mapped[int] = mapped_column(Integer)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    options_json: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    chosen_room_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)


class OperationalModel(Base):
    __tablename__ = "operational_models"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    version: Mapped[str] = mapped_column(String(80))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    artifact_path: Mapped[str] = mapped_column(String(500))
    metrics_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("facility_id", "version"),)


class ExperimentScenarioVersion(Base):
    __tablename__ = "experiment_scenario_versions"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    series_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    config_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64))
    rationale: Mapped[str] = mapped_column(String(500))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("facility_id", "series_id", "revision"),)


class ExperimentRun(Base, TimestampMixin):
    __tablename__ = "experiment_runs"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    scenario_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiment_scenario_versions.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    results_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ResearchProtocol(Base):
    __tablename__ = "research_protocols"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"))
    model_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    question: Mapped[str] = mapped_column(String(1000))
    design: Mapped[str] = mapped_column(String(30))
    config_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("design IN ('MANUAL_ONLY','COUNTERBALANCED','SHADOW')"),)


class ResearchCase(Base):
    __tablename__ = "research_cases"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    protocol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_protocols.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    features_json: Mapped[dict] = mapped_column(JSON)
    synthetic_label: Mapped[str] = mapped_column(String(2))
    source_row_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("protocol_id", "ordinal"),
                     CheckConstraint("synthetic_label IN ('P1','P2','P3','P4','P5')"),)


class CaseReview(Base):
    __tablename__ = "research_case_reviews"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_cases.id"), index=True)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(String(2))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("case_id", "reviewer_id"),
                     CheckConstraint("label IN ('P1','P2','P3','P4','P5')"),)


class CaseAdjudication(Base):
    __tablename__ = "research_case_adjudications"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_cases.id"), unique=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(String(2))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("label IN ('P1','P2','P3','P4','P5')"),)


class ResearchTrial(Base):
    __tablename__ = "research_trials"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    protocol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_protocols.id"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_cases.id"))
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    arm: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="STARTED")
    consent_ref: Mapped[str] = mapped_column(String(160))
    inference_json: Mapped[dict] = mapped_column(JSON, default=dict)
    final_label: Mapped[str | None] = mapped_column(String(2), nullable=True)
    response_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("protocol_id", "case_id", "participant_id"),
                     CheckConstraint("arm IN ('MANUAL','ADVISORY','EXPLANATION','SHADOW')"),
                     CheckConstraint("status IN ('STARTED','COMPLETED')"),
                     CheckConstraint("final_label IS NULL OR final_label IN ('P1','P2','P3','P4','P5')"),
                     CheckConstraint("(status = 'STARTED' AND completed_at IS NULL AND final_label IS NULL) OR (status = 'COMPLETED' AND completed_at IS NOT NULL AND final_label IS NOT NULL)"),
                     Index("uq_research_trial_active", "protocol_id", "participant_id", unique=True,
                           postgresql_where=text("status = 'STARTED'"), sqlite_where=text("status = 'STARTED'")))


class ResearchStudyRun(Base, TimestampMixin):
    __tablename__ = "research_study_runs"
    id = uuidpk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    protocol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_protocols.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    results_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_summary: Mapped[str | None] = mapped_column(String(240), nullable=True)
    __table_args__ = (CheckConstraint("status IN ('PENDING','RUNNING','COMPLETED','FAILED')"),)

