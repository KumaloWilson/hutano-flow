import uuid
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.commands import CommandRoute
from app.database import get_db
from app.models import Facility, Patient, QueuePolicy, ServicePoint, User, UserRole, Visit, utcnow
from app.schemas import APIModel
from app.security import CurrentUser, hash_password, require_roles, role_names
from app.services.audit import record_audit, enqueue_event

router = APIRouter(prefix="/api/v1", route_class=CommandRoute)
ROLES = {"ADMIN", "RECEPTIONIST", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY", "MANAGER", "RESEARCHER"}


class UserCreate(APIModel):
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=255)
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    roles: list[str] = Field(min_length=1)


class UserChange(APIModel):
    roles: list[str] = Field(min_length=1)
    active: bool


class PolicyCreate(APIModel):
    mode: Literal["FCFS", "URGENCY_FIRST", "HYBRID"] = "HYBRID"
    urgency_weight: float = Field(default=1., ge=0, le=10)
    waiting_weight: float = Field(default=.25, ge=0, le=10)
    capacity_weight: float = Field(default=0., ge=0, le=10)
    long_wait_warning_minutes: int = Field(default=60, ge=1, le=1440)
    reason: str = Field(min_length=5, max_length=240)


class Reason(APIModel):
    reason: str = Field(min_length=5, max_length=240)


class Retention(APIModel):
    retention_days: int = Field(ge=1, le=3650)
    confirmation: Literal["REDACT EXPIRED SYNTHETIC PSEUDONYMS"]


class PointConfiguration(APIModel):
    version: int = Field(ge=1)
    name: str = Field(min_length=3, max_length=80)
    operating_hours: dict[str, str]
    allowed_routes: list[Literal["consultation", "pharmacy", "laboratory", "discharge"]]
    reason: str = Field(min_length=5, max_length=240)

    @field_validator("operating_hours")
    @classmethod
    def hours(cls, value):
        from datetime import time
        if set(value) != {"open", "close"}:
            raise ValueError("Use open and close local times")
        if time.fromisoformat(value["open"]) >= time.fromisoformat(value["close"]):
            raise ValueError("Closing time must follow opening time")
        return value


@router.post("/admin/service-points/{point_id}/configuration")
def configure_point(point_id: uuid.UUID, payload: PointConfiguration, user: User = Depends(require_roles("ADMIN")),
                    db: Session = Depends(get_db, scope="function"), key: str = Header(alias="Idempotency-Key")):
    point = db.scalar(select(ServicePoint).where(ServicePoint.id == point_id, ServicePoint.facility_id == user.facility_id))
    if not point:
        raise HTTPException(404, "Service point not found")
    if point.version != payload.version:
        raise HTTPException(409, "Service point changed; refresh before configuring")
    existing = set(db.scalars(select(ServicePoint.type).where(ServicePoint.facility_id == user.facility_id, ServicePoint.active.is_(True))))
    if not set(payload.allowed_routes) <= existing:
        raise HTTPException(422, "Routes must refer to active service points")
    old = {"name": point.name, "operating_hours": point.operating_hours, "allowed_routes": point.allowed_routes}
    point.name, point.operating_hours, point.allowed_routes = payload.name, payload.operating_hours, payload.allowed_routes
    point.version += 1
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="service_point.configured", object_type="ServicePoint",
        object_id=point.id, correlation_id=key, old=old, new=payload.model_dump(exclude={"reason"}), reason=payload.reason)
    enqueue_event(db, facility_id=user.facility_id, topic="service_point.capacity_changed", aggregate_id=point.id, version=point.version)
    return {"id": str(point.id), "version": point.version}


@router.get("/admin/users")
def users(user: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db, scope="function")):
    return [{"id": str(u.id), "email": u.email, "display_name": u.display_name, "roles": sorted(role_names(u)), "active": u.active}
        for u in db.scalars(select(User).where(User.facility_id == user.facility_id))]


@router.post("/admin/users", status_code=201)
def create_user(payload: UserCreate, user: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db, scope="function"),
                key: str = Header(alias="Idempotency-Key")):
    if not set(payload.roles) <= ROLES:
        raise HTTPException(422, "Unknown role")
    created = User(facility_id=user.facility_id, email=payload.email.lower(), display_name=payload.display_name,
                   password_hash=hash_password(payload.password))
    db.add(created)
    db.flush()
    for role in set(payload.roles):
        db.add(UserRole(user_id=created.id, facility_id=user.facility_id, role=role))
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="user.created", object_type="User", object_id=created.id,
        correlation_id=key, new={"roles": sorted(payload.roles)})
    return {"id": str(created.id), "created": True}


@router.post("/admin/users/{user_id}")
def update_user(user_id: uuid.UUID, payload: UserChange, user: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db, scope="function"),
                key: str = Header(alias="Idempotency-Key")):
    if not set(payload.roles) <= ROLES or user_id == user.id:
        raise HTTPException(422, "Unknown role or unsupported self-modification")
    target = db.scalar(select(User).where(User.id == user_id, User.facility_id == user.facility_id))
    if not target:
        raise HTTPException(404, "User not found")
    old = {"roles": sorted(role_names(target)), "active": target.active}
    target.roles.clear()
    db.flush()
    target.roles = [UserRole(facility_id=user.facility_id, role=role) for role in set(payload.roles)]
    target.active = payload.active
    target.session_version += 1
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="user.access_changed", object_type="User", object_id=target.id,
        correlation_id=key, old=old, new={"roles": payload.roles, "active": payload.active})
    return {"id": str(target.id), "updated": True, "sessions_revoked": True}


@router.get("/queue/policies")
def policies(user: CurrentUser, db: Session = Depends(get_db, scope="function")):
    return [{"id": str(p.id), "version": p.version, "active": p.active, "config": p.config_json,
             "approved_by": str(p.approved_by) if p.approved_by else None}
        for p in db.scalars(select(QueuePolicy).where(QueuePolicy.facility_id == user.facility_id).order_by(QueuePolicy.created_at.desc()))]


@router.post("/queue/policies", status_code=201)
def propose_policy(payload: PolicyCreate, user: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db, scope="function"),
                   key: str = Header(alias="Idempotency-Key")):
    policy = QueuePolicy(facility_id=user.facility_id, version=f"{payload.mode.lower()}-{uuid.uuid4().hex[:12]}",
        active=False, config_json={**payload.model_dump(exclude={"reason"}), "ageing_scope": "within_confirmed_urgency_only",
                                  "clinical_review_status": "PENDING_SYNTHETIC_REVIEW"})
    db.add(policy)
    db.flush()
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="policy.proposed", object_type="QueuePolicy", object_id=policy.id,
        correlation_id=key, new=policy.config_json, reason=payload.reason)
    return {"id": str(policy.id), "version": policy.version, "active": False, "requires_clinician_review": True}


@router.post("/queue/policies/{policy_id}/approve")
def approve_policy(policy_id: uuid.UUID, payload: Reason, user: User = Depends(require_roles("TRIAGE_NURSE", "CLINICIAN")),
                   db: Session = Depends(get_db, scope="function"), key: str = Header(alias="Idempotency-Key")):
    policy = db.scalar(select(QueuePolicy).where(QueuePolicy.id == policy_id, QueuePolicy.facility_id == user.facility_id))
    if not policy:
        raise HTTPException(404, "Policy not found")
    for old in db.scalars(select(QueuePolicy).where(QueuePolicy.facility_id == user.facility_id)):
        old.active = False
    policy.active, policy.approved_by, policy.effective_at = True, user.id, utcnow()
    policy.config_json = {**policy.config_json, "clinical_review_status": "REVIEWED_FOR_SYNTHETIC_DEMO"}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="policy.approved", object_type="QueuePolicy", object_id=policy.id,
        correlation_id=key, new=policy.config_json, reason="Clinician policy review recorded")
    enqueue_event(db, facility_id=user.facility_id, topic="queue.rank_changed", aggregate_id=policy.id, payload={"policy_version": policy.version})
    return {"id": str(policy.id), "active": True, "version": policy.version}


@router.get("/admin/facility")
def facility(user: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db, scope="function")):
    f = db.get(Facility, user.facility_id)
    return {"name": f.name, "timezone": f.timezone, "demo_mode": f.demo_mode, "retention_days": f.retention_days}


@router.post("/admin/retention/redact")
def redact(payload: Retention, user: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db, scope="function"), key: str = Header(alias="Idempotency-Key")):
    f = db.get(Facility, user.facility_id)
    f.retention_days = payload.retention_days
    threshold = utcnow() - timedelta(days=payload.retention_days)
    count = 0
    for patient in db.scalars(select(Patient).where(Patient.facility_id == user.facility_id, Patient.synthetic_flag.is_(True), Patient.created_at < threshold)):
        active = db.scalar(select(Visit.id).where(Visit.patient_id == patient.id, Visit.status.not_in(["COMPLETED", "CANCELLED", "LEFT_WITHOUT_SERVICE"])))
        if not active:
            patient.pseudonym = None
            patient.year_of_birth = None
            patient.sex = None
            count += 1
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="retention.pseudonyms_redacted", object_type="Facility", object_id=f.id,
        correlation_id=key, new={"retention_days": payload.retention_days, "count": count})
    return {"redacted_patients": count, "audit_preserved": True}
