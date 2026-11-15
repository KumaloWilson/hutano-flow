import asyncio
import csv
import hashlib
import io
import json
import secrets
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, select, and_, or_, case
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.commands import CommandRoute
from app.access import operational, can_access_visit, allowed_services, service_action
from app.database import SessionLocal, get_db
from app.ml.pipeline import validate_frame, explain_prediction, advisory_for_display, FEATURES
from app.models import (
    AuditEvent,
    ClinicianDecision,
    Dataset,
    EventOutbox,
    EpisodeCorrection,
    EncounterNote,
    IdempotencyRecord,
    Job,
    ModelVersion,
    Observation,
    Patient,
    PriorityRecommendation,
    QueueEntry,
    QueueStateEvent,
    ResearchFeedback,
    ServiceEpisode,
    ServicePoint,
    SimulationRun,
    SimulationScenario,
    TriageAssessment,
    User,
    Visit,
    utcnow,
)
from app.schemas import (
    AvailabilityUpdate,
    DatasetMetadata,
    EpisodeComplete,
    EpisodeStart,
    EpisodeStateChange,
    EpisodeTransfer,
    FeedbackCreate,
    LoginRequest,
    PatientCreate,
    PatientStatusLookup,
    QueueCall,
    QueueOverride,
    RecommendationDecisionCreate,
    RegisterVisit,
    SimulationCreate,
    TriageCreate,
    VisitCreate,
    ModelTrain,
    ModelReview,
    InferenceRequest,
    TimestampCorrection,
    PasswordChange,
)
from app.security import (
    CurrentUser,
    client_key,
    create_session_token,
    csrf_token,
    burn_password_check,
    hash_password,
    password_problems,
    session_auth_time,
    rate_limiter,
    require_roles,
    role_names,
    token_digest,
    status_secret,
    verify_password,
    decode_session_token,
)
from app.services.audit import enqueue_event, record_audit
from app.services.events import visible_event, invalidation, RESEARCH_TOPICS
from app.contracts import UserResponse, VisitResponse, ServicePointResponse, QueueResponse
from app.services.queue import atomic_call, rank_queue, latest_urgency
from app.services.workflow import (
    ACTIVE_VISIT_STATES,
    add_episode,
    new_public_tokens,
    require_episode,
    require_visit,
    transition_episode,
)
from app.simulation.engine import run_comparison, summary


app = FastAPI(
    title="Hutano Flow Research API",
    version="1.0.0",
    description="Research prototype only — not authorised for clinical use.",
)
app.router.route_class = CommandRoute
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "Last-Event-ID"],
)


@app.middleware("http")
async def security_headers_and_csrf(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    unsafe = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    public_query = request.url.path == "/api/v1/patient-status/lookup"
    if unsafe and request.headers.get("Origin") and request.headers["Origin"] not in settings.allowed_origins:
        return JSONResponse(status_code=403, content={"error": "Origin is not allowed", "request_id": request.state.request_id})
    if unsafe and request.cookies.get("hutano_session") and not public_query:
        cookie = request.cookies.get("hutano_csrf")
        header = request.headers.get("X-CSRF-Token")
        if not cookie or not header or not secrets.compare_digest(cookie, header):
            return JSONResponse(
                status_code=403,
                content={"error": "CSRF validation failed", "request_id": request.state.request_id},
            )
    if unsafe:
        maximum = 5_100_000 if request.url.path.endswith("/import") else 65_536
        try:
            declared = int(request.headers.get("Content-Length", "0"))
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid content length", "request_id": request.state.request_id})
        if declared > maximum:
            return JSONResponse(status_code=413, content={"error": "Request body is too large", "request_id": request.state.request_id})
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > maximum:
                return JSONResponse(status_code=413, content={"error": "Request body is too large", "request_id": request.state.request_id})
            chunks.append(chunk)
        request._body = b"".join(chunks)
    try:
        response = await call_next(request)
    except IntegrityError:
        response = JSONResponse(status_code=409, content={"error": "Command conflicts with existing state", "request_id": request.state.request_id})
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": str(exc.detail), "request_id": getattr(request.state, "request_id", None)},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "Input validation failed",
            "details": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()],
            "request_id": getattr(request.state, "request_id", None),
        },
    )


def like_pattern(text: str) -> str:
    """Substring pattern with LIKE wildcards escaped, so `%` or `_` cannot list every record."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def require_idempotency(value: str | None) -> str:
    if not value or len(value) < 8 or len(value) > 100:
        raise HTTPException(status_code=400, detail="A valid Idempotency-Key header is required")
    return value


def commit(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="The command conflicts with existing state") from exc


def user_view(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "facility_id": str(user.facility_id),
        "roles": sorted(role_names(user)),
        "research_mode": settings.research_mode,
        "must_change_password": bool(user.must_change_password),
        "session_idle_minutes": settings.session_idle_minutes,
    }


def episode_view(episode: ServiceEpisode) -> dict:
    return {
        "id": str(episode.id),
        "service_point_id": str(episode.service_point_id),
        "service_point": episode.service_point.name,
        "service_type": episode.service_point.type,
        "sequence_no": episode.sequence_no,
        "status": episode.status,
        "queued_at": episode.queued_at,
        "called_at": episode.called_at,
        "started_at": episode.started_at,
        "ended_at": episode.ended_at,
        "version": episode.version,
        "recall_count": episode.queue_entry.recall_count if episode.queue_entry else 0,
        "missed_calls": episode.queue_entry.missed_calls if episode.queue_entry else 0,
        "deferred_until": episode.queue_entry.deferred_until if episode.queue_entry else None,
        "corrections": [{"id": str(c.id), "original": c.original_values, "corrected": c.corrected_values, "created_at": c.created_at} for c in episode.corrections],
    }


def visit_view(visit: Visit, include_patient: bool = True, user: User | None = None) -> dict:
    result = {
        "id": str(visit.id),
        "public_token": visit.public_token,
        "status": visit.status,
        "visit_type": visit.visit_type,
        "arrival_at": visit.arrival_at,
        "registered_at": visit.registered_at,
        "completed_at": visit.completed_at,
        "planned_services": visit.planned_services,
        "version": visit.version,
        "synthetic": visit.patient.synthetic_flag,
        "entry_mode": visit.entry_mode or "LIVE",
        "episodes": [episode_view(item) for item in visit.episodes],
    }
    if include_patient:
        result["patient"] = {
            "id": str(visit.patient.id),
            "pseudonym": visit.patient.pseudonym,
            "age_band": visit.patient.age_band,
            "sex": visit.patient.sex,
            "synthetic": visit.patient.synthetic_flag,
        }
    if user and not role_names(user) & {"ADMIN", "RECEPTIONIST", "CLINICIAN", "TRIAGE_NURSE"}:
        result.pop("patient", None)
        result["episodes"] = [item for item in result["episodes"] if item["service_type"] in allowed_services(user)]
    return result


@app.get("/health")
def health(db: Session = Depends(get_db, scope="function")):
    db.execute(select(1))
    return {"status": "ok", "research_mode": settings.research_mode, "service": "hutano-flow-api"}


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def set_session_cookies(response: Response, session_token: str, csrf: str | None = None) -> None:
    response.set_cookie("hutano_session", session_token, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", max_age=settings.session_minutes * 60, path="/")
    if csrf:
        response.set_cookie("hutano_csrf", csrf, httponly=False, secure=settings.cookie_secure,
                            samesite="strict", max_age=settings.session_minutes * 60, path="/")


def locked_response(minutes: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"Too many failed sign-in attempts. Try again in {minutes} minutes or ask an administrator to unlock the account.",
        headers={"Retry-After": str(minutes * 60)},
    )


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    # Per real client address (see security.client_ip); a whole clinic no longer shares one bucket.
    rate_limiter.check(client_key(request, "login"), 30, 60)
    email = payload.email.lower()
    now = utcnow()
    threshold, minutes = settings.login_lockout_threshold, settings.login_lockout_minutes
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.active:
        # Same Argon2 cost and the same lockout behaviour as a real account, so neither
        # timing nor the lockout message reveals which email addresses exist.
        burn_password_check(payload.password)
        email_key = "login-email:" + hashlib.sha256(email.encode()).hexdigest()[:24]
        try:
            rate_limiter.guard(email_key, threshold, minutes * 60)
        except HTTPException:
            raise locked_response(minutes)
        rate_limiter.record(email_key)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.locked_until and _aware(user.locked_until) > now:
        burn_password_check(payload.password)
        raise locked_response(minutes)
    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= threshold:
            user.locked_until = now + timedelta(minutes=minutes)
            user.failed_login_count = 0
            record_audit(db, facility_id=user.facility_id, actor_id=None, action="auth.account_locked", object_type="User",
                         object_id=user.id, correlation_id=request.state.request_id,
                         new={"locked_minutes": minutes}, reason="Consecutive failed sign-in attempts")
            db.commit()
            raise locked_response(minutes)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()
    csrf = csrf_token()
    set_session_cookies(response, create_session_token(user), csrf)
    return {"user": user_view(user), "csrf_token": csrf}


@app.post("/api/v1/auth/refresh")
def refresh_session(request: Request, response: Response, user: CurrentUser):
    """Extend the idle window after genuine user activity. Never past the absolute lifetime."""
    payload = decode_session_token(request.cookies.get("hutano_session", ""))
    auth_time = session_auth_time(payload)
    token = create_session_token(user, auth_time=auth_time)
    set_session_cookies(response, token)
    expires = datetime.fromtimestamp(decode_session_token(token)["exp"], tz=timezone.utc)
    return {"expires_at": expires, "absolute_expires_at": auth_time + timedelta(minutes=settings.session_minutes)}


@app.post("/api/v1/auth/password")
def change_password(payload: PasswordChange, request: Request, response: Response, user: CurrentUser,
                    db: Session = Depends(get_db, scope="function")):
    rate_limiter.check(f"password:{user.id}", 10, 300)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=422, detail="Choose a password you have not just used")
    problems = password_problems(payload.new_password, user.email, user.display_name)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    user.session_version += 1  # signs out every other device
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="auth.password_changed", object_type="User",
                 object_id=user.id, correlation_id=request.state.request_id, new={"sessions_revoked": True})
    db.commit()
    csrf = csrf_token()
    set_session_cookies(response, create_session_token(user), csrf)
    return {"user": user_view(user), "csrf_token": csrf, "other_sessions_revoked": True}


@app.post("/api/v1/auth/logout")
def logout(response: Response, user: CurrentUser, db: Session = Depends(get_db, scope="function")):
    user.session_version += 1
    db.commit()
    response.delete_cookie("hutano_session", path="/")
    response.delete_cookie("hutano_csrf", path="/")
    return {"status": "signed_out"}


@app.get("/api/v1/me", response_model=UserResponse)
def me(user: CurrentUser):
    return user_view(user)


@app.get("/api/v1/patients")
def list_patients(
    user: User = Depends(require_roles("ADMIN", "RECEPTIONIST", "TRIAGE_NURSE", "CLINICIAN")),
    db: Session = Depends(get_db, scope="function"),
    q: str | None = Query(default=None, max_length=120),
):
    statement = select(Patient).where(Patient.facility_id == user.facility_id)
    if q:
        try:
            identifier = uuid.UUID(q)
            statement = statement.where(Patient.id == identifier)
        except ValueError:
            statement = statement.where(Patient.pseudonym.ilike(like_pattern(q[:80]), escape="\\"))
    patients = db.scalars(statement.order_by(Patient.created_at.desc()).limit(100)).all()
    return [
        {
            "id": str(item.id),
            "pseudonym": item.pseudonym,
            "age_band": item.age_band,
            "sex": item.sex,
            "synthetic": item.synthetic_flag,
            "created_at": item.created_at,
        }
        for item in patients
    ]


@app.post("/api/v1/patients", status_code=201)
def create_patient(
    payload: PatientCreate,
    user: User = Depends(require_roles("ADMIN", "RECEPTIONIST")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    patient = Patient(facility_id=user.facility_id, **payload.model_dump())
    db.add(patient)
    db.flush()
    result = {"id": str(patient.id), "pseudonym": patient.pseudonym, "synthetic": True}
    record_audit(
        db,
        facility_id=user.facility_id,
        actor_id=user.id,
        action="patient.created",
        object_type="Patient",
        object_id=patient.id,
        correlation_id=key,
        new={"synthetic": True},
    )
    commit(db)
    return result


@app.get("/api/v1/visits", response_model=list[VisitResponse], response_model_exclude_none=True)
def list_visits(user: CurrentUser, db: Session = Depends(get_db, scope="function"), status_filter: str | None = None, q: str | None = Query(default=None,max_length=120), offset:int=Query(default=0,ge=0), limit:int=Query(default=100,ge=1,le=200)):
    operational(user)
    statement = select(Visit).where(Visit.facility_id == user.facility_id)
    if status_filter == "OPEN":
        statement=statement.where(Visit.status.in_(ACTIVE_VISIT_STATES))
    elif status_filter:
        statement = statement.where(Visit.status == status_filter)
    if q:
        pattern=like_pattern(q)
        matches=[Visit.public_token.ilike(pattern, escape="\\")]
        if role_names(user)&{"ADMIN","RECEPTIONIST","CLINICIAN","TRIAGE_NURSE"}:
            matches.append(Visit.patient.has(Patient.pseudonym.ilike(pattern, escape="\\")))
        try: matches.append(Visit.id==uuid.UUID(q))
        except ValueError: pass
        statement=statement.where(or_(*matches))
    if not role_names(user)&{"ADMIN","RECEPTIONIST","CLINICIAN","TRIAGE_NURSE"}:
        statement=statement.where(Visit.episodes.any(ServiceEpisode.service_point.has(ServicePoint.type.in_(allowed_services(user)))))
    visits = db.scalars(statement.order_by(case((Visit.status.in_(ACTIVE_VISIT_STATES),0),else_=1),Visit.arrival_at.desc(),Visit.id).offset(offset).limit(limit)).unique().all()
    return [visit_view(item, user=user) for item in visits if can_access_visit(user, item)]


@app.post("/api/v1/visits", status_code=201, response_model=VisitResponse, response_model_exclude_none=True)
def create_visit(
    payload: VisitCreate,
    user: User = Depends(require_roles("ADMIN", "RECEPTIONIST")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    patient = db.scalar(
        select(Patient).where(Patient.id == payload.patient_id, Patient.facility_id == user.facility_id)
    )
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    duplicate = db.scalar(
        select(Visit.id).where(
            Visit.patient_id == patient.id,
            Visit.facility_id == user.facility_id,
            Visit.status.in_(ACTIVE_VISIT_STATES),
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Patient already has an active visit")
    configured = set(db.scalars(select(ServicePoint.type).where(ServicePoint.facility_id == user.facility_id)))
    if not payload.planned_services or any(item not in configured for item in payload.planned_services):
        raise HTTPException(status_code=422, detail="Planned services must use configured service point types")
    public, opaque, digest = new_public_tokens(db, user.facility_id)
    visit_id = uuid.uuid4()
    opaque = status_secret(visit_id, public)
    digest = token_digest(opaque)
    from zoneinfo import ZoneInfo
    from app.models import Facility
    arrival = payload.arrival_at or utcnow()
    if arrival.tzinfo is None or arrival > utcnow():
        raise HTTPException(422, "Arrival must include a timezone and cannot be in the future")
    if (utcnow() - arrival).total_seconds() > 86400:
        raise HTTPException(422, "Use the audited baseline import for historical observations")
    visit = Visit(
        id=visit_id,
        facility_id=user.facility_id,
        patient_id=patient.id,
        public_token=public,
        token_day=utcnow().astimezone(ZoneInfo(db.get(Facility, user.facility_id).timezone)).date(),
        token_secret_hash=digest,
        arrival_at=arrival,
        status="REGISTERING",
        visit_type=payload.visit_type,
        planned_services=payload.planned_services,
    )
    db.add(visit)
    db.flush()
    add_episode(db, visit=visit, point_type="registration", actor_id=user.id)
    result = visit_view(visit)
    result["opaque_status_token"] = opaque
    record_audit(
        db,
        facility_id=user.facility_id,
        actor_id=user.id,
        action="visit.created",
        object_type="Visit",
        object_id=visit.id,
        correlation_id=key,
        new={"status": visit.status, "synthetic": True},
    )
    enqueue_event(
        db,
        facility_id=user.facility_id,
        topic="visit.created",
        aggregate_id=visit.id,
        payload={"visit_id": str(visit.id), "status": visit.status},
    )
    commit(db)
    return result


@app.get("/api/v1/visits/{visit_id}", response_model=VisitResponse, response_model_exclude_none=True)
def get_visit(visit_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db, scope="function")):
    visit = require_visit(db, visit_id, user.facility_id)
    if not can_access_visit(user, visit):
        raise HTTPException(404, "Visit not found")
    return visit_view(visit, user=user)


@app.post("/api/v1/visits/{visit_id}/register")
def register_visit(
    visit_id: uuid.UUID,
    payload: RegisterVisit,
    user: User = Depends(require_roles("ADMIN", "RECEPTIONIST")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    visit = require_visit(db, visit_id, user.facility_id)
    if visit.status != "REGISTERING" or visit.version != payload.version:
        raise HTTPException(status_code=409, detail="Visit is not in a current registering state")
    registration = next((item for item in visit.episodes if item.service_point.type == "registration"), None)
    if not registration:
        raise HTTPException(status_code=409, detail="Registration episode is missing")
    registration.called_at = registration.called_at or utcnow()
    registration.started_at = registration.started_at or registration.called_at
    transition_episode(
        db,
        registration,
        expected={"WAITING", "CALLED", "IN_SERVICE"},
        target="COMPLETED",
        actor_id=user.id,
        expected_version=registration.version,
    )
    visit.registered_at = utcnow()
    visit.status = "AWAITING_TRIAGE"
    visit.version += 1
    add_episode(db, visit=visit, point_type="triage", actor_id=user.id)
    result = {"visit_id": str(visit.id), "status": visit.status, "version": visit.version}
    record_audit(
        db,
        facility_id=user.facility_id,
        actor_id=user.id,
        action="visit.registered",
        object_type="Visit",
        object_id=visit.id,
        correlation_id=key,
        old={"status": "REGISTERING"},
        new={"status": visit.status},
    )
    enqueue_event(db, facility_id=user.facility_id, topic="visit.state_changed", aggregate_id=visit.id, version=visit.version, payload=result)
    commit(db)
    return result


@app.post("/api/v1/visits/{visit_id}/triage", status_code=201)
def triage_visit(
    visit_id: uuid.UUID,
    payload: TriageCreate,
    user: User = Depends(require_roles("TRIAGE_NURSE", "CLINICIAN")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    visit = require_visit(db, visit_id, user.facility_id)
    if visit.status != "AWAITING_TRIAGE" or visit.version != payload.version:
        raise HTTPException(status_code=409, detail="Visit must be awaiting triage with a current version")
    if payload.recommendation_decision != "NO_MODEL" and not payload.recommendation_id:
        raise HTTPException(status_code=422, detail="Recommendation decision requires a recommendation ID")
    if payload.recommendation_decision == "NO_MODEL" and payload.recommendation_id:
        raise HTTPException(422, "Choose an explicit review decision for the referenced recommendation")
    if payload.recommendation_id:
        suggestion = db.scalar(select(PriorityRecommendation).where(PriorityRecommendation.id == payload.recommendation_id,
            PriorityRecommendation.facility_id == user.facility_id, PriorityRecommendation.visit_id == visit.id))
        if not suggestion:
            raise HTTPException(404, "Recommendation not found for this visit")
        if payload.recommendation_decision == "ACCEPT" and suggestion.suggestion != payload.configured_urgency:
            raise HTTPException(422, "Accepted category must match the advisory suggestion")
    assessment = TriageAssessment(
        facility_id=user.facility_id,
        visit_id=visit.id,
        assessor_id=user.id,
        configured_urgency=payload.configured_urgency,
        reason=payload.reason,
        feature_snapshot={key: value is not None for key, value in payload.observations.items()},
    )
    db.add(assessment)
    from app.patients import FIELDS
    for field_code, value in payload.observations.items():
        if len(field_code) > 80:
            raise HTTPException(status_code=422, detail="Observation field code is too long")
        db.add(
            Observation(
                facility_id=user.facility_id,
                visit_id=visit.id,
                field_code=field_code,
                value=None if value is None else str(value),
                unit=FIELDS.get(field_code, ('', None))[1],
                entered_by=user.id,
            )
        )
    triage_episode = next(
        (item for item in visit.episodes if item.service_point.type == "triage" and item.status not in {"COMPLETED", "CANCELLED"}),
        None,
    )
    if not triage_episode:
        raise HTTPException(status_code=409, detail="Active triage episode is missing")
    if not triage_episode.called_at:
        triage_episode.called_at = utcnow()
    if not triage_episode.started_at:
        triage_episode.started_at = triage_episode.called_at
    transition_episode(
        db,
        triage_episode,
        expected={"WAITING", "CALLED", "IN_SERVICE"},
        target="COMPLETED",
        actor_id=user.id,
        expected_version=triage_episode.version,
    )
    db.add(
        ClinicianDecision(
            facility_id=user.facility_id,
            recommendation_id=payload.recommendation_id,
            visit_id=visit.id,
            clinician_id=user.id,
            decision=payload.recommendation_decision,
            final_urgency=payload.configured_urgency,
            justification=payload.reason,
        )
    )
    visit.status = "ESCALATION_REQUIRED" if payload.escalation_required else "ACTIVE"
    visit.version += 1
    if not payload.escalation_required:
        add_episode(db, visit=visit, point_type="consultation", actor_id=user.id)
    result = {
        "visit_id": str(visit.id),
        "status": visit.status,
        "confirmed_urgency": payload.configured_urgency,
        "version": visit.version,
        "model_suggestion_applied_automatically": False,
    }
    record_audit(
        db,
        facility_id=user.facility_id,
        actor_id=user.id,
        action="triage.confirmed",
        object_type="Visit",
        object_id=visit.id,
        correlation_id=key,
        new={"confirmed_urgency": payload.configured_urgency, "status": visit.status},
        reason="Clinician assessment recorded",
        metadata={"recommendation_decision": payload.recommendation_decision, "rationale_hash": hashlib.sha256((payload.reason or "").encode()).hexdigest()},
    )
    enqueue_event(db, facility_id=user.facility_id, topic="episode.queued" if not payload.escalation_required else "visit.state_changed", aggregate_id=visit.id, version=visit.version, payload={"visit_id": str(visit.id), "status": visit.status})
    commit(db)
    return result


@app.get("/api/v1/service-points", response_model=list[ServicePointResponse])
def service_points(user: CurrentUser, db: Session = Depends(get_db, scope="function")):
    points = db.scalars(
        select(ServicePoint).where(ServicePoint.facility_id == user.facility_id).order_by(ServicePoint.name)
    ).all()
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "type": item.type,
            "capacity": item.capacity,
            "active": item.active,
            "outage_state": item.outage_state,
            "outage_reason": item.outage_reason,
            "operating_hours": item.operating_hours,
            "allowed_routes": item.allowed_routes,
            "version": item.version,
        }
        for item in points
    ]


@app.get("/api/v1/service-points/{point_id}/queue", response_model=QueueResponse)
def get_queue(point_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db, scope="function")):
    operational(user)
    point = db.scalar(select(ServicePoint).where(ServicePoint.id == point_id, ServicePoint.facility_id == user.facility_id))
    if not point or point.type not in allowed_services(user):
        raise HTTPException(404, "Service point not found")
    return {"service_point_id": str(point_id), "generated_at": utcnow(), "entries": rank_queue(db, user.facility_id, point_id)}


@app.post("/api/v1/queue/{entry_id}/call")
def call_entry(
    entry_id: uuid.UUID,
    payload: QueueCall,
    user: User = Depends(require_roles("ADMIN", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    entry = db.scalar(
        select(QueueEntry).where(QueueEntry.id == entry_id, QueueEntry.facility_id == user.facility_id).with_for_update(of=QueueEntry)
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    service_action(user, entry.episode)
    eligible = rank_queue(db, user.facility_id, entry.service_point_id)
    if str(entry.id) not in {row["queue_entry_id"] for row in eligible}:
        raise HTTPException(409, "Entry is not eligible for routine service")
    if eligible and eligible[0]["queue_entry_id"] != str(entry.id) and not entry.manual_pin:
        raise HTTPException(409, "Call the first recommended entry or record a clinician override")
    atomic_call(db, entry, user.id, payload.version)
    db.add(QueueStateEvent(facility_id=user.facility_id, episode_id=entry.episode_id, actor_id=user.id,
                          from_status="WAITING", to_status="CALLED"))
    result = {"queue_entry_id": str(entry.id), "status": "CALLED", "version": payload.version + 1}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="episode.called", object_type="QueueEntry", object_id=entry.id, correlation_id=key, old={"status": "WAITING"}, new={"status": "CALLED"})
    enqueue_event(db, facility_id=user.facility_id, topic="episode.called", aggregate_id=entry.episode_id, version=payload.version + 1, payload=result)
    commit(db)
    return result


@app.post("/api/v1/episodes/{episode_id}/start")
def start_episode(
    episode_id: uuid.UUID,
    payload: EpisodeStart,
    user: User = Depends(require_roles("ADMIN", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    episode = require_episode(db, episode_id, user.facility_id)
    service_action(user, episode)
    transition_episode(db, episode, expected={"CALLED", "PAUSED"}, target="IN_SERVICE", actor_id=user.id, expected_version=payload.version)
    result = {"episode_id": str(episode.id), "status": episode.status, "version": episode.version, "started_at": episode.started_at}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="episode.started", object_type="ServiceEpisode", object_id=episode.id, correlation_id=key, new={"status": episode.status}, reason=payload.reason)
    enqueue_event(db, facility_id=user.facility_id, topic="episode.started", aggregate_id=episode.id, version=episode.version, payload=result)
    commit(db)
    return result


@app.post("/api/v1/episodes/{episode_id}/complete")
def complete_episode(
    episode_id: uuid.UUID,
    payload: EpisodeComplete,
    user: User = Depends(require_roles("ADMIN", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    episode = require_episode(db, episode_id, user.facility_id)
    service_action(user, episode)
    if payload.next_service_type and payload.next_service_type not in episode.service_point.allowed_routes:
        raise HTTPException(422, "Route is not configured for this service point")
    transition_episode(db, episode, expected={"IN_SERVICE"}, target="COMPLETED", actor_id=user.id, expected_version=payload.version)
    episode.operational_note = payload.operational_note
    if payload.operational_note:
        db.add(EncounterNote(facility_id=user.facility_id,episode_id=episode.id,actor_id=user.id,text=payload.operational_note))
    visit = episode.visit
    next_episode = None
    if payload.next_service_type:
        next_episode = add_episode(db, visit=visit, point_type=payload.next_service_type, actor_id=user.id)
        visit.status = "ACTIVE"
    else:
        visit.status = "COMPLETED"
        visit.completed_at = utcnow()
    visit.version += 1
    result = {
        "episode_id": str(episode.id),
        "status": episode.status,
        "visit_status": visit.status,
        "next_episode_id": str(next_episode.id) if next_episode else None,
        "version": episode.version,
    }
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="episode.completed", object_type="ServiceEpisode", object_id=episode.id, correlation_id=key, old={"status": "IN_SERVICE"}, new={"status": episode.status, "visit_status": visit.status})
    enqueue_event(db, facility_id=user.facility_id, topic="episode.completed", aggregate_id=episode.id, version=episode.version, payload=result)
    commit(db)
    return result


@app.post("/api/v1/episodes/{episode_id}/transfer", status_code=201)
def transfer_episode(
    episode_id: uuid.UUID,
    payload: EpisodeTransfer,
    user: User = Depends(require_roles("ADMIN", "CLINICIAN", "SERVICE_PROVIDER")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    episode = require_episode(db, episode_id, user.facility_id)
    service_action(user, episode)
    if payload.next_service_type not in episode.service_point.allowed_routes:
        raise HTTPException(422, "Route is not configured for this service point")
    if episode.version != payload.version or episode.status not in {"WAITING", "CALLED", "PAUSED"}:
        raise HTTPException(status_code=409, detail="Episode cannot be transferred from its current state")
    old_status = episode.status
    from app.resources import release_assignment
    release_assignment(db,episode)
    episode.status = "TRANSFERRED"
    episode.version += 1
    if episode.queue_entry:
        episode.queue_entry.status = "TRANSFERRED"
        episode.queue_entry.version += 1
        episode.queue_entry.manual_pin = False
        episode.queue_entry.pin_rank = None
    db.flush()
    created = add_episode(db, visit=episode.visit, point_type=payload.next_service_type, actor_id=user.id)
    db.add(QueueStateEvent(facility_id=user.facility_id, episode_id=episode.id, actor_id=user.id, from_status=old_status, to_status="TRANSFERRED"))
    result = {"episode_id": str(episode.id), "status": "TRANSFERRED", "next_episode_id": str(created.id)}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="episode.transferred", object_type="ServiceEpisode", object_id=episode.id, correlation_id=key, old={"status": old_status}, new=result, reason=payload.reason)
    enqueue_event(db, facility_id=user.facility_id, topic="episode.queued", aggregate_id=created.id, payload={"episode_id": str(created.id), "status": "WAITING"})
    commit(db)
    return result


@app.post("/api/v1/episodes/{episode_id}/state")
def change_episode_state(
    episode_id: uuid.UUID,
    payload: EpisodeStateChange,
    user: User = Depends(require_roles("ADMIN", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    endpoint = f"episodes.{episode_id}.state"
    episode = require_episode(db, episode_id, user.facility_id)
    service_action(user, episode)
    if episode.version != payload.version:
        raise HTTPException(status_code=409, detail="Episode changed; refresh before updating state")
    if payload.action in {"RECALL", "DEFER"}:
        return missed_call(db, user, episode, payload, key)
    transitions = {
        "PAUSE": ({"CALLED", "IN_SERVICE"}, "PAUSED"),
        "NO_SHOW": ({"WAITING", "CALLED"}, "NO_SHOW"),
        "CANCEL": ({"PLANNED", "WAITING", "CALLED", "PAUSED"}, "CANCELLED"),
        "REOPEN_WAITING": ({"PAUSED", "NO_SHOW"}, "WAITING"),
    }
    allowed, target = transitions[payload.action]
    if episode.status not in allowed:
        raise HTTPException(status_code=409, detail=f"Cannot {payload.action.lower()} an episode in {episode.status}")
    previous = episode.status
    if target in {"NO_SHOW", "CANCELLED", "WAITING"}:
        from app.resources import release_assignment
        release_assignment(db,episode)
    episode.status = target
    episode.version += 1
    if target == "WAITING":
        if episode.started_at:
            raise HTTPException(409, "Resume a paused service with Start; do not erase its service history")
        episode.queued_at = utcnow()
        episode.called_at = None
        episode.started_at = None
        if episode.queue_entry:
            episode.queue_entry.joined_at = episode.queued_at
    if target == "PAUSED" and episode.started_at:
        episode.paused_at = utcnow()
    if episode.queue_entry:
        episode.queue_entry.status = target
        episode.queue_entry.version += 1
        if target != "WAITING":
            episode.queue_entry.manual_pin = False
            episode.queue_entry.pin_rank = None
    if target == "NO_SHOW":
        episode.visit.status = "LEFT_WITHOUT_SERVICE"
        episode.visit.version += 1
    elif target == "CANCELLED" and not any(
        item.status in {"WAITING", "CALLED", "IN_SERVICE", "PAUSED"}
        for item in episode.visit.episodes if item.id != episode.id
    ):
        episode.visit.status = "CANCELLED"
        episode.visit.version += 1
    elif target == "WAITING" and episode.visit.status in {"LEFT_WITHOUT_SERVICE", "CANCELLED"}:
        episode.visit.status = "AWAITING_TRIAGE" if episode.service_point.type == "triage" else "ACTIVE"
        episode.visit.version += 1
    db.add(QueueStateEvent(facility_id=user.facility_id, episode_id=episode.id, actor_id=user.id, from_status=previous, to_status=target, metadata_json={"reason_present": True}))
    result = {"episode_id": str(episode.id), "from_status": previous, "status": target, "version": episode.version}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action=f"episode.{payload.action.lower()}", object_type="ServiceEpisode", object_id=episode.id, correlation_id=key, old={"status": previous}, new={"status": target}, reason=payload.reason)
    enqueue_event(db, facility_id=user.facility_id, topic="visit.state_changed", aggregate_id=episode.visit_id, version=episode.visit.version, payload={"episode_id": str(episode.id), "status": target})
    commit(db)
    return result


MAX_MISSED_CALLS = 3
DEFAULT_DEFER_MINUTES = 10


def missed_call(db: Session, user: User, episode: ServiceEpisode, payload: EpisodeStateChange, key: str) -> dict:
    """RECALL re-announces a called patient; DEFER returns them to WAITING with their place.

    Neither erases history: the first call remains in queue_state_events, and a deferred
    patient's queued_at is preserved so their measured wait still runs from first arrival.
    """
    entry = episode.queue_entry
    if episode.status != "CALLED" or entry is None:
        raise HTTPException(409, "Only a called patient can be recalled or deferred")
    now = utcnow()
    if payload.action == "RECALL":
        entry.recall_count = (entry.recall_count or 0) + 1
        entry.last_recalled_at = now
        entry.version += 1
        episode.version += 1
        result = {"episode_id": str(episode.id), "status": "CALLED", "recall_count": entry.recall_count, "version": episode.version}
        record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="episode.recalled", object_type="ServiceEpisode",
                     object_id=episode.id, correlation_id=key, new={"recall_count": entry.recall_count}, reason=payload.reason)
        enqueue_event(db, facility_id=user.facility_id, topic="episode.called", aggregate_id=episode.id, version=episode.version,
                      payload={"episode_id": str(episode.id), "status": "CALLED"})
        commit(db)
        return result
    if (entry.missed_calls or 0) + 1 > MAX_MISSED_CALLS:
        raise HTTPException(409, f"Patient has missed {MAX_MISSED_CALLS} calls; record a no-show or ask a clinician to keep their place")
    from app.resources import release_assignment
    release_assignment(db, episode)
    minutes = payload.defer_minutes or DEFAULT_DEFER_MINUTES
    entry.missed_calls = (entry.missed_calls or 0) + 1
    entry.deferred_until = now + timedelta(minutes=minutes)
    entry.recall_count = 0
    entry.status = "WAITING"
    entry.manual_pin = False
    entry.pin_rank = None
    entry.version += 1
    episode.status = "WAITING"
    episode.called_at = None
    episode.version += 1
    db.add(QueueStateEvent(facility_id=user.facility_id, episode_id=episode.id, actor_id=user.id, from_status="CALLED",
                           to_status="WAITING", metadata_json={"missed_call": True, "defer_minutes": minutes}))
    result = {"episode_id": str(episode.id), "from_status": "CALLED", "status": "WAITING", "missed_calls": entry.missed_calls,
              "deferred_until": entry.deferred_until, "version": episode.version}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="episode.deferred", object_type="ServiceEpisode",
                 object_id=episode.id, correlation_id=key, old={"status": "CALLED"},
                 new={"status": "WAITING", "missed_calls": entry.missed_calls, "defer_minutes": minutes}, reason=payload.reason)
    enqueue_event(db, facility_id=user.facility_id, topic="visit.state_changed", aggregate_id=episode.visit_id,
                  version=episode.visit.version, payload={"episode_id": str(episode.id), "status": "WAITING"})
    commit(db)
    return jsonable_encoder(result)


@app.post("/api/v1/queue/override")
def override_queue(
    payload: QueueOverride,
    user: User = Depends(require_roles("TRIAGE_NURSE", "CLINICIAN")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    entry = db.scalar(
        select(QueueEntry).where(QueueEntry.id == payload.queue_entry_id, QueueEntry.facility_id == user.facility_id).with_for_update(of=QueueEntry)
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    if entry.status != "WAITING" or entry.version != payload.version:
        raise HTTPException(status_code=409, detail="Only a current waiting entry can be overridden")
    before = rank_queue(db, user.facility_id, entry.service_point_id)
    previous_order = next((item["recommended_order"] for item in before if item["queue_entry_id"] == str(entry.id)), None)
    entry.manual_pin = not payload.release
    entry.pin_rank = min(payload.new_rank, len(before)) if not payload.release else None
    entry.pin_note = payload.note
    entry.version += 1
    result = {
        "queue_entry_id": str(entry.id),
        "previous_order": previous_order,
        "new_order": entry.pin_rank,
        "reason": payload.reason_code,
        "policy_version": entry.policy_version,
        "version": entry.version,
    }
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="clinician.override_recorded", object_type="QueueEntry", object_id=entry.id, correlation_id=key, old={"order": previous_order}, new={"order": entry.pin_rank}, reason=payload.reason_code, metadata={"policy_version": before[0]["policy_version"] if before else entry.policy_version, "note_present": bool(payload.note), "previous_order": previous_order, "new_order": entry.pin_rank, "released": payload.release})
    enqueue_event(db, facility_id=user.facility_id, topic="clinician.override_recorded", aggregate_id=entry.id, version=entry.version, payload={"queue_entry_id": str(entry.id), "new_order": payload.new_rank})
    commit(db)
    return result


@app.post("/api/v1/service-points/{point_id}/availability")
def update_availability(
    point_id: uuid.UUID,
    payload: AvailabilityUpdate,
    user: User = Depends(require_roles("ADMIN", "CLINICIAN", "SERVICE_PROVIDER")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    point = db.scalar(select(ServicePoint).where(ServicePoint.id == point_id, ServicePoint.facility_id == user.facility_id))
    if not point:
        raise HTTPException(status_code=404, detail="Service point not found")
    if point.version != payload.version:
        raise HTTPException(status_code=409, detail="Service point changed; refresh first")
    old = {"capacity": point.capacity, "outage_state": point.outage_state}
    point.capacity = payload.capacity
    point.outage_state = payload.outage_state
    point.outage_reason = payload.reason
    point.version += 1
    result = {"id": str(point.id), "capacity": point.capacity, "outage_state": point.outage_state, "version": point.version}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="service_point.capacity_changed", object_type="ServicePoint", object_id=point.id, correlation_id=key, old=old, new=result, reason=payload.reason)
    enqueue_event(db, facility_id=user.facility_id, topic="service_point.capacity_changed", aggregate_id=point.id, version=point.version, payload=result)
    commit(db)
    return result


@app.get("/api/v1/recommendations/{visit_id}")
def get_recommendations(
    visit_id: uuid.UUID,
    user: User = Depends(require_roles("TRIAGE_NURSE", "CLINICIAN")),
    db: Session = Depends(get_db, scope="function"),
):
    require_visit(db, visit_id, user.facility_id)
    recommendations = db.scalars(select(PriorityRecommendation).where(PriorityRecommendation.visit_id == visit_id).order_by(PriorityRecommendation.created_at.desc())).all()
    if not recommendations:
        return {
            "available": False,
            "message": "Model unavailable — clinician assessment required",
            "warning": "The manual clinician-confirmed queue remains fully available.",
        }
    return [
        {
            "id": str(item.id), "suggestion": item.suggestion, "confidence": item.confidence,
            "model_version": item.model_version, "explanation": advisory_for_display(item.explanation_json),
            "requires_clinician_review": True, "warning": "EXPERIMENTAL — NOT VALIDATED FOR PATIENT CARE",
        }
        for item in recommendations
    ]


@app.post("/api/v1/recommendations/{recommendation_id}/decision", status_code=201)
def recommendation_decision(
    recommendation_id: uuid.UUID,
    payload: RecommendationDecisionCreate,
    user: User = Depends(require_roles("TRIAGE_NURSE", "CLINICIAN")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    recommendation = db.scalar(select(PriorityRecommendation).where(PriorityRecommendation.id == recommendation_id, PriorityRecommendation.facility_id == user.facility_id))
    if not recommendation:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if payload.decision == "ACCEPT" and recommendation.suggestion != payload.final_urgency:
        raise HTTPException(422, "Accepted category must match the advisory suggestion")
    decision = ClinicianDecision(facility_id=user.facility_id, recommendation_id=recommendation.id, visit_id=recommendation.visit_id, clinician_id=user.id, decision=payload.decision, final_urgency=payload.final_urgency, justification=payload.justification)
    db.add(decision)
    db.flush()
    result = {"id": str(decision.id), "decision": decision.decision, "final_urgency": decision.final_urgency, "authoritative_applied": False}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="recommendation.reviewed", object_type="PriorityRecommendation", object_id=recommendation.id, correlation_id=key, new={"decision": payload.decision, "final_urgency": payload.final_urgency}, reason="Clinician model review recorded")
    commit(db)
    return result


def restricted_status(db: Session, opaque_token: str) -> dict:
    visit = db.scalar(select(Visit).where(Visit.token_secret_hash == token_digest(opaque_token)))
    if not visit:
        raise HTTPException(status_code=404, detail="Status token was not found")
    current = next((item for item in reversed(visit.episodes) if item.status not in {"COMPLETED", "CANCELLED", "TRANSFERRED", "SKIPPED"}), None)
    ahead = None
    estimate = None
    stage = "Complete" if visit.status == "COMPLETED" else "Preparing next stage"
    if visit.status == "ESCALATION_REQUIRED":
        return {"token": visit.public_token, "stage": "Please speak with staff", "status": "STAFF_ASSISTANCE",
                "people_ahead": None, "estimated_wait": None, "updated_at": utcnow(), "research_notice": "Research prototype — not for clinical use"}
    if current:
        stage = current.service_point.name
        if current.queue_entry and current.status == "WAITING":
            ranked = rank_queue(db, visit.facility_id, current.service_point_id)
            position = next((item["recommended_order"] for item in ranked if item["queue_entry_id"] == str(current.queue_entry.id)), None)
            ahead = max(0, position - 1) if position else None
            point = current.service_point
            if point.capacity > 0 and ahead is not None:
                samples = db.scalars(select(ServiceEpisode).where(ServiceEpisode.service_point_id == point.id,
                    ServiceEpisode.status == "COMPLETED", ServiceEpisode.started_at.is_not(None), ServiceEpisode.ended_at.is_not(None))).all()
                durations = [max(0, (ep.ended_at - ep.started_at).total_seconds() / 60 - ep.paused_seconds / 60) for ep in samples]
                if len(durations) >= 5:
                    import numpy as np
                    busy = db.scalar(select(func.count(ServiceEpisode.id)).where(ServiceEpisode.service_point_id == point.id,
                        ServiceEpisode.status.in_(["CALLED", "IN_SERVICE", "PAUSED"]))) or 0
                    workload = ahead + busy
                    estimate = {"minimum_minutes": int(workload * float(np.percentile(durations, 25)) / point.capacity),
                        "maximum_minutes": int((workload + 1) * float(np.percentile(durations, 90)) / point.capacity) + 1,
                        "warning": "Estimate only; may change. Measured synthetic service durations; residual service approximated.", "sample_size": len(durations)}
                    from app.operational_prediction import estimate_duration
                    from app.resources import room_snapshot
                    prediction=estimate_duration(db,current)
                    rooms=room_snapshot(db,visit.facility_id,point.id)
                    effective_capacity=min(point.capacity,sum(r['staffed'] for r in rooms)) if rooms else point.capacity
                    if effective_capacity<=0:
                        estimate=None
                    elif not prediction.get('available'):
                        estimate['minimum_minutes']=int(workload*float(np.percentile(durations,25))/effective_capacity)
                        estimate['maximum_minutes']=int((workload+1)*float(np.percentile(durations,90))/effective_capacity)+1
                    elif prediction.get('available'):
                        estimate={'minimum_minutes':int(workload*prediction['minimum_minutes']/effective_capacity),
                            'maximum_minutes':int((workload+1)*prediction['maximum_minutes']/effective_capacity)+1,
                            'warning':'Estimate only; synthetic duration predictions and current staffing. This queue range is not a calibrated waiting-time guarantee.', 'sample_size':len(durations)}
    return {
        "token": visit.public_token,
        "stage": stage,
        "status": current.status if current else visit.status,
        "people_ahead": ahead,
        "estimated_wait": estimate,
        "updated_at": utcnow(),
        "research_notice": "Research prototype — not for clinical use",
    }


@app.post("/api/v1/patient-status/lookup")
def patient_status_lookup(payload: PatientStatusLookup, request: Request, db: Session = Depends(get_db, scope="function")):
    # Tokens carry 192+ bits of secret, so guessing is infeasible; the strict limit is on
    # *misses* per real client address. Valid holders are limited per token (the page polls
    # every 10 s), and a generous per-address ceiling allows a waiting room behind one NAT.
    miss_key = client_key(request, "patient-status-miss")
    rate_limiter.guard(miss_key, 20, 60)
    rate_limiter.check(client_key(request, "patient-status-ip"), 600, 60)
    rate_limiter.check("patient-status-token:" + hashlib.sha256(payload.token.encode()).hexdigest()[:24], 20, 60)
    try:
        return restricted_status(db, payload.token)
    except HTTPException as exc:
        if exc.status_code == 404:
            rate_limiter.record(miss_key)
        raise


@app.get("/api/v1/patient-status/{opaque_token}", deprecated=True)
def patient_status_compat(opaque_token: str, request: Request, db: Session = Depends(get_db, scope="function")):
    rate_limiter.check(client_key(request, "patient-status"), 20, 60)
    raise HTTPException(410, "Use POST /api/v1/patient-status/lookup to keep private tokens out of URLs")


@app.get("/api/v1/events")
async def events(request: Request, user: CurrentUser, cursor: str | None = None):
    facility_id = user.facility_id
    cursor = request.headers.get("Last-Event-ID") or cursor
    actor_id, session_version = user.id, user.session_version
    is_research = not role_names(user) & {"ADMIN", "RECEPTIONIST", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY"}

    def read_cursor():
        with SessionLocal() as lookup:
            try:
                event = lookup.get(EventOutbox, uuid.UUID(cursor))
            except ValueError:
                return None
            return (event.created_at, event.id) if event and event.facility_id == facility_id else None

    def poll_batch(last_created, last_id):
        # Synchronous database checkout/queries must never block the ASGI loop:
        # it must remain free to close other requests and release pooled connections.
        with SessionLocal() as db:
            current = db.get(User, actor_id)
            if not current or not current.active or current.session_version != session_version:
                return None
            query = select(EventOutbox).where(EventOutbox.facility_id == facility_id)
            if is_research:
                query = query.where(EventOutbox.topic.in_(RESEARCH_TOPICS))
            if last_created:
                query = query.where(or_(EventOutbox.created_at > last_created,
                    and_(EventOutbox.created_at == last_created, EventOutbox.id > last_id))) if last_id else query.where(EventOutbox.created_at >= last_created)
            rows = db.scalars(query.order_by(EventOutbox.created_at, EventOutbox.id).limit(100)).all()
            batch = []
            for item in rows:
                if visible_event(db, current, item):
                    batch.append(f"id: {item.id}\nevent: {item.topic}\ndata: {json.dumps(invalidation(item))}\n\n")
                last_created, last_id = item.created_at, item.id
            return batch, last_created, last_id

    async def stream():
        last_created, last_id = utcnow(), None
        if cursor:
            position = await run_in_threadpool(read_cursor)
            if position:
                last_created, last_id = position
            else:
                yield "event: reset\ndata: {}\n\n"
        while not await request.is_disconnected():
            try:
                decode_session_token(request.cookies.get("hutano_session", ""))
            except HTTPException:
                return
            polled = await run_in_threadpool(poll_batch, last_created, last_id)
            if polled is None:
                return
            batch, last_created, last_id = polled
            # The read transaction has closed before network waits or backpressure.
            for message in batch:
                yield message
            yield ": keepalive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.get("/api/v1/analytics/overview")
def analytics_overview(
    user: User = Depends(require_roles("ADMIN", "MANAGER", "RESEARCHER")),
    db: Session = Depends(get_db, scope="function"),
    from_date: date | None = None, to_date: date | None = None,
):
    from app.services.analytics import overview
    return overview(db, user.facility_id, from_date, to_date)


@app.get("/api/v1/analytics/service-points")
def analytics_service_points(
    user: User = Depends(require_roles("ADMIN", "MANAGER", "RESEARCHER")), db: Session = Depends(get_db, scope="function")
):
    return analytics_overview(user, db)["service_points"]


@app.get("/api/v1/analytics/export")
def analytics_export(
    user: User = Depends(require_roles("ADMIN", "RESEARCHER")), db: Session = Depends(get_db, scope="function"), format: str = "csv", from_date: date | None = None, to_date: date | None = None,
):
    overview = analytics_overview(user, db, from_date, to_date)
    from fastapi.encoders import jsonable_encoder
    from app.services.reports import bar_svg
    overview = jsonable_encoder(overview)
    if format == "json":
        return JSONResponse(overview, headers={"Content-Disposition": "attachment; filename=hutano-analytics.json"})
    if format == "svg":
        return Response(bar_svg("Mean waiting time by service point", {p["name"]:p["waiting"]["mean"] for p in overview["service_points"]}), media_type="image/svg+xml", headers={"Content-Disposition": "attachment; filename=hutano-analytics.svg"})
    if format != "csv":
        raise HTTPException(422, "Choose csv, json or svg")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["research_label", overview["research_label"]])
    for field in ["report_title", "source_type", "dataset_hash", "dataset_hash_basis", "units", "model_version", "observation_period", "reporting_filter", "policy_version", "timestamp_basis", "definitions"]:
        writer.writerow(["# " + field, json.dumps(overview[field], sort_keys=True)])
    writer.writerow(["service_point", "completed", "mean_wait_minutes", "p90_wait_minutes", "mean_service_minutes"])
    for point in overview["service_points"]:
        writer.writerow([point["name"], point["completed"], point["waiting"]["mean"], point["waiting"]["p90"], point["service"]["mean"]])
    return Response(content=buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=hutano-analytics.csv"})


@app.post("/api/v1/simulations", status_code=202)
def create_simulation(
    payload: SimulationCreate,
    user: User = Depends(require_roles("ADMIN", "MANAGER", "RESEARCHER")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    rate_limiter.check(f"simulation:{user.id}", 10, 300)
    scenario = SimulationScenario(facility_id=user.facility_id, owner_id=user.id, name=payload.name, scenario_json=payload.model_dump(mode="json"), synthetic_flag=True)
    db.add(scenario)
    db.flush()
    run = SimulationRun(facility_id=user.facility_id, scenario_id=scenario.id, policy="COMPARISON", seed=payload.seed, replications=payload.replications, status="PENDING", started_at=utcnow())
    db.add(run)
    db.flush()
    rate = payload.arrival_rate_per_hour * (1.6 if payload.high_load else 1.0)
    config = payload.model_dump(exclude={"name", "high_load", "consultation_servers"})
    config.update(servers=payload.consultation_servers, arrival_rate_per_hour=rate)
    job = Job(facility_id=user.facility_id, type="SIMULATION", config_json=config, result_ref=str(run.id))
    db.add(job)
    db.flush()
    result = {"id": str(run.id), "job_id": str(job.id), "status": run.status, "results": {}}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="simulation.submitted", object_type="SimulationRun", object_id=run.id, correlation_id=key, new={"seed": run.seed, "replications": run.replications, "synthetic": True})
    commit(db)
    return result


@app.get("/api/v1/simulations")
def list_simulations(user: User = Depends(require_roles("ADMIN", "MANAGER", "RESEARCHER")), db: Session = Depends(get_db, scope="function")):
    rows=db.execute(select(SimulationRun,SimulationScenario.name).join(SimulationScenario,SimulationScenario.id==SimulationRun.scenario_id).where(SimulationRun.facility_id==user.facility_id).order_by(SimulationRun.started_at.desc()).limit(30)).all()
    return [{"id":str(run.id),"name":name,"status":run.status,"seed":run.seed,"replications":run.replications,"started_at":run.started_at} for run,name in rows]


@app.get("/api/v1/simulations/{run_id}")
def get_simulation(run_id: uuid.UUID, user: User = Depends(require_roles("ADMIN", "MANAGER", "RESEARCHER")), db: Session = Depends(get_db, scope="function")):
    run = db.scalar(select(SimulationRun).where(SimulationRun.id == run_id, SimulationRun.facility_id == user.facility_id))
    if not run:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return {"id": str(run.id), "status": run.status, "seed": run.seed, "replications": run.replications, "results": run.results_json}


@app.get("/api/v1/simulations/{run_id}/export")
def export_simulation(run_id: uuid.UUID, user: User = Depends(require_roles("ADMIN", "MANAGER", "RESEARCHER")), db: Session = Depends(get_db, scope="function"), format: str = "json"):
    run = db.scalar(select(SimulationRun).where(SimulationRun.id == run_id, SimulationRun.facility_id == user.facility_id))
    if not run:
        raise HTTPException(status_code=404, detail="Simulation not found")
    if run.status != "COMPLETED":
        raise HTTPException(409, "Simulation is not yet complete")
    if format == "csv":
        from app.services.reports import comparison_csv
        return Response(comparison_csv(run.results_json), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=simulation-{run.id}.csv"})
    if format == "svg":
        from app.services.reports import bar_svg
        return Response(bar_svg("Outpatient waiting time — identical seeded inputs", {name:r["waiting_minutes"]["mean"] for name,r in run.results_json["policies"].items()}), media_type="image/svg+xml", headers={"Content-Disposition": f"attachment; filename=simulation-{run.id}.svg"})
    if format != "json":
        raise HTTPException(422, "Choose csv, json or svg")
    return JSONResponse(run.results_json, headers={"Content-Disposition": f"attachment; filename=simulation-{run.id}.json"})


DIRECT_IDENTIFIER_COLUMNS = {"name", "full_name", "national_id", "phone", "email", "address", "passport"}


@app.post("/api/v1/research/datasets/import", status_code=201)
async def import_dataset(
    file: UploadFile = File(...),
    name: str = Form(...),
    source_type: str = Form(...),
    consent_basis_note: str = Form(...),
    synthetic_flag: bool = Form(True),
    user: User = Depends(require_roles("ADMIN", "RESEARCHER")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    rate_limiter.check(f"dataset:{user.id}", 5, 300)
    try:
        metadata = DatasetMetadata(name=name, source_type=source_type, consent_basis_note=consent_basis_note, synthetic_flag=synthetic_flag)
    except ValidationError as exc:
        raise HTTPException(422, "Valid synthetic dataset metadata and provenance are required") from exc
    if not synthetic_flag and settings.research_mode:
        raise HTTPException(status_code=422, detail="This demonstration build imports synthetic data only")
    if file.content_type not in {"text/csv", "application/vnd.ms-excel", "text/plain"}:
        raise HTTPException(status_code=422, detail="Only CSV files are accepted")
    raw = await file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Dataset exceeds the upload limit")
    try:
        frame = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="CSV could not be parsed") from exc
    columns = {str(column).strip().lower() for column in frame.columns}
    rejected = sorted(columns.intersection(DIRECT_IDENTIFIER_COLUMNS))
    if rejected:
        raise HTTPException(status_code=422, detail=f"Direct identifier columns are not accepted: {', '.join(rejected)}")
    try:
        quality = validate_frame(frame)
    except (ValueError, TypeError) as error:
        raise HTTPException(422, str(error)) from error
    digest = hashlib.sha256(raw).hexdigest()
    directory = Path(settings.model_artifact_dir) / str(user.facility_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"dataset-{digest}.csv"
    path.write_bytes(raw)
    path.chmod(0o600)
    dataset = Dataset(facility_id=user.facility_id, name=metadata.name, source_type=metadata.source_type, dataset_hash=digest, consent_basis_note=metadata.consent_basis_note, schema_json=quality, row_count=len(frame), synthetic_flag=metadata.synthetic_flag, file_path=str(path))
    db.add(dataset)
    db.flush()
    result = {"id": str(dataset.id), "dataset_hash": digest, "row_count": len(frame), "synthetic": dataset.synthetic_flag, "columns": list(frame.columns), "missing": dataset.schema_json["missing"]}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="dataset.imported", object_type="Dataset", object_id=dataset.id, correlation_id=key, new={"hash": digest, "rows": len(frame), "synthetic": True})
    commit(db)
    return result


@app.get("/api/v1/research/datasets")
def list_datasets(user: User = Depends(require_roles("ADMIN", "RESEARCHER")), db: Session = Depends(get_db, scope="function")):
    rows = db.scalars(select(Dataset).where(Dataset.facility_id == user.facility_id).order_by(Dataset.created_at.desc())).all()
    return [{"id": str(item.id), "name": item.name, "source_type": item.source_type, "dataset_hash": item.dataset_hash, "row_count": item.row_count, "synthetic": item.synthetic_flag, "schema": item.schema_json} for item in rows]


@app.post("/api/v1/research/models/train", status_code=202)
def train_model(
    payload: ModelTrain,
    user: User = Depends(require_roles("ADMIN", "RESEARCHER")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    rate_limiter.check(f"train:{user.id}", 3, 300)
    query = select(Dataset).where(Dataset.facility_id == user.facility_id, Dataset.synthetic_flag.is_(True), Dataset.source_type == "SYNTHETIC", Dataset.file_path.is_not(None))
    if payload.dataset_id:
        query = query.where(Dataset.id == payload.dataset_id)
    dataset = db.scalar(query.order_by(Dataset.created_at).limit(1))
    if not dataset:
        raise HTTPException(status_code=409, detail="Synthetic demonstration dataset metadata is missing; reseed the database")
    job = Job(facility_id=user.facility_id, type="MODEL_TRAIN", config_json={"dataset_id": str(dataset.id), "seed": payload.seed})
    db.add(job)
    db.flush()
    result = {"id": str(job.id), "job_id": str(job.id), "status": "PENDING", "warning": "Synthetic software demonstration — not clinically validated"}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="model.training_submitted", object_type="Job", object_id=job.id, correlation_id=key, new={"dataset_hash": dataset.dataset_hash, "synthetic": True})
    commit(db)
    return result


@app.get("/api/v1/research/models")
def list_models(user: User = Depends(require_roles("ADMIN", "RESEARCHER")), db: Session = Depends(get_db, scope="function")):
    models = db.scalars(select(ModelVersion).where(ModelVersion.facility_id == user.facility_id).order_by(ModelVersion.created_at.desc())).all()
    return [{"id": str(item.id), "model_name": item.model_name, "version": item.version, "status": item.status, "active": item.active, "metrics": item.metrics_json, "warning": "EXPERIMENTAL — NOT VALIDATED FOR PATIENT CARE"} for item in models]


@app.get("/api/v1/research/jobs/{job_id}")
def get_job(job_id: uuid.UUID, user: User = Depends(require_roles("ADMIN", "RESEARCHER", "MANAGER")), db: Session = Depends(get_db, scope="function")):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.facility_id == user.facility_id))
    if not job:
        raise HTTPException(404, "Job not found")
    return {"id": str(job.id), "type": job.type, "status": job.status, "result_ref": job.result_ref,
            "attempt_count": job.attempt_count, "error": job.error_summary}


@app.get("/api/v1/research/jobs")
def list_jobs(user: User = Depends(require_roles("ADMIN", "RESEARCHER", "MANAGER")), db: Session = Depends(get_db, scope="function")):
    return [{"id": str(j.id), "type": j.type, "status": j.status, "result_ref": j.result_ref, "created_at": j.created_at, "error": j.error_summary}
            for j in db.scalars(select(Job).where(Job.facility_id == user.facility_id).order_by(Job.created_at.desc()).limit(50))]


@app.get("/api/v1/models/reviewable")
def reviewable_models(user: User = Depends(require_roles("TRIAGE_NURSE", "CLINICIAN")), db: Session = Depends(get_db, scope="function")):
    return [{"id": str(m.id), "version": m.version, "status": m.status, "active": m.active, "metrics": m.metrics_json}
        for m in db.scalars(select(ModelVersion).where(ModelVersion.facility_id == user.facility_id))]


@app.post("/api/v1/research/models/{model_id}/lifecycle")
def model_lifecycle(model_id: uuid.UUID, payload: ModelReview, user: CurrentUser,
                    db: Session = Depends(get_db, scope="function"), idempotency_key: str = Header(alias="Idempotency-Key")):
    model = db.scalar(select(ModelVersion).where(ModelVersion.id == model_id, ModelVersion.facility_id == user.facility_id))
    if not model:
        raise HTTPException(404, "Model not found")
    roles = role_names(user)
    old = {"status": model.status, "active": model.active}
    if payload.action == "REVIEW":
        if not roles & {"TRIAGE_NURSE", "CLINICIAN"}:
            raise HTTPException(403, "An authorised clinician must review this research model")
        if model.status != "EXPERIMENTAL":
            raise HTTPException(409, "Only an experimental model can be reviewed")
        model.reviewed_by, model.review_note, model.status = user.id, payload.reason, "REVIEWED"
    else:
        if "ADMIN" not in roles:
            raise HTTPException(403, "Administrator permission required")
        if payload.action == "ACTIVATE":
            if model.status != "REVIEWED" or not model.reviewed_by:
                raise HTTPException(409, "Clinician research review is required before demo activation")
            for other in db.scalars(select(ModelVersion).where(ModelVersion.facility_id == user.facility_id)):
                other.active = False
            model.active = True
        else:
            model.active = False
            if payload.action == "RETIRE":
                model.status = "RETIRED"
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="model.lifecycle_changed", object_type="ModelVersion",
        object_id=model.id, correlation_id=idempotency_key, old=old, new={"status": model.status, "active": model.active}, reason="Research model lifecycle review recorded")
    enqueue_event(db, facility_id=user.facility_id, topic="model.registry_changed", aggregate_id=model.id, payload={"active": model.active})
    return {"id": str(model.id), "status": model.status, "active": model.active,
            "warning": "Reviewed for synthetic demonstration only; never clinical validation"}


@app.post("/api/v1/visits/{visit_id}/recommendation", status_code=201)
def infer_recommendation(visit_id: uuid.UUID, payload: InferenceRequest,
    user: User = Depends(require_roles("CLINICIAN", "TRIAGE_NURSE")), db: Session = Depends(get_db, scope="function"),
    idempotency_key: str = Header(alias="Idempotency-Key")):
    visit = require_visit(db, visit_id, user.facility_id)
    if set(payload.features) - set(FEATURES):
        raise HTTPException(422, "Unapproved model feature")
    model = db.scalar(select(ModelVersion).where(ModelVersion.facility_id == user.facility_id, ModelVersion.active.is_(True), ModelVersion.status == "REVIEWED"))
    if not model:
        return {"available": False, "message": "Model unavailable — clinician assessment required"}
    try:
        explanation = advisory_for_display(explain_prediction(model.artifact_path, payload.features))
    except (FileNotFoundError, OSError):
        return {"available": False, "message": "Model unavailable — clinician assessment required"}
    recommendation = PriorityRecommendation(facility_id=user.facility_id, visit_id=visit.id,
        algorithm_type="SYNTHETIC_LOGISTIC_REGRESSION", model_version=model.version,
        suggestion=explanation["suggestion"], confidence=explanation["confidence"], explanation_json=explanation)
    db.add(recommendation)
    db.flush()
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="model.recommendation_recorded", object_type="PriorityRecommendation",
        object_id=recommendation.id, correlation_id=idempotency_key, new={"model_version": model.version, "abstained": explanation["abstained"]})
    enqueue_event(db, facility_id=user.facility_id, topic="model.recommendation_ready", aggregate_id=visit.id, payload={"recommendation_id": str(recommendation.id)})
    return {"id": str(recommendation.id), "available": True, "model_version": model.version, **explanation,
            "model_suggestion_applied_automatically": False}


@app.get("/api/v1/research/models/{model_id}/metrics")
def model_metrics(model_id: uuid.UUID, user: User = Depends(require_roles("ADMIN", "RESEARCHER")), db: Session = Depends(get_db, scope="function")):
    model = db.scalar(select(ModelVersion).where(ModelVersion.id == model_id, ModelVersion.facility_id == user.facility_id))
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"id": str(model.id), "version": model.version, "status": model.status, "metrics": model.metrics_json, "limitations": ["Synthetic labels are not clinical ground truth", "No real-world calibration or safety validation", "Predictions always require clinician review"]}


@app.post("/api/v1/research/feedback", status_code=201)
def research_feedback(
    payload: FeedbackCreate,
    user: User = Depends(require_roles("ADMIN", "MANAGER", "RESEARCHER")),
    db: Session = Depends(get_db, scope="function"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = require_idempotency(idempotency_key)
    feedback = ResearchFeedback(facility_id=user.facility_id, role_group=payload.role_group, task_id=payload.task_id, response_json=payload.response, consent_ref=payload.consent_ref)
    db.add(feedback)
    db.flush()
    result = {"id": str(feedback.id), "recorded": True}
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="research_feedback.recorded", object_type="ResearchFeedback", object_id=feedback.id, correlation_id=key, new={"role_group": payload.role_group, "task_id": payload.task_id})
    commit(db)
    return result


@app.get("/api/v1/audit")
def audit_log(
    user: User = Depends(require_roles("ADMIN", "MANAGER", "RESEARCHER")),
    db: Session = Depends(get_db, scope="function"),
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    reason: str | None = None,
    cursor: uuid.UUID | None = None,
):
    query = select(AuditEvent).where(AuditEvent.facility_id == user.facility_id)
    if action:
        query = query.where(AuditEvent.action == action)
    if actor_id:
        query = query.where(AuditEvent.actor_id == actor_id)
    if reason:
        query = query.where(AuditEvent.reason.icontains(reason[:240], autoescape=True))
    if cursor:
        from sqlalchemy import or_, and_
        previous = db.scalar(select(AuditEvent).where(AuditEvent.id == cursor, AuditEvent.facility_id == user.facility_id))
        if not previous:
            raise HTTPException(404, "Audit cursor not found")
        query = query.where(or_(AuditEvent.occurred_at < previous.occurred_at,
            and_(AuditEvent.occurred_at == previous.occurred_at, AuditEvent.id < previous.id)))
    rows = db.scalars(query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(250)).all()
    return [{"id": str(item.id), "actor_id": str(item.actor_id) if item.actor_id else None, "action": item.action, "object_type": item.object_type, "object_id": item.object_id, "reason": item.reason, "occurred_at": item.occurred_at, "correlation_id": item.correlation_id, "metadata": item.metadata_json} for item in rows]


@app.get("/api/v1/research/feedback/summary")
def feedback_summary(user: User = Depends(require_roles("ADMIN", "RESEARCHER", "MANAGER")), db: Session = Depends(get_db, scope="function")):
    rows = db.scalars(select(ResearchFeedback).where(ResearchFeedback.facility_id == user.facility_id)).all()
    durations = [r.response_json["duration_seconds"] for r in rows if "duration_seconds" in r.response_json]
    trust = [r.response_json["trust_rating"] for r in rows if "trust_rating" in r.response_json]
    return {"research_label": "Controlled usability observations; descriptive results only", "tasks_observed":len(rows),
        "tasks_completed":sum(r.response_json.get("completed") is True for r in rows),
        "task_duration_seconds":summary(durations), "error_count":sum(r.response_json.get("errors",0) for r in rows),
        "trust_rating_1_to_5":summary(trust), "trust_instrument":"Unvalidated descriptive question, not SUS or a clinical safety measure",
        "limitations":["Convenience sample; no generalisation", "Consent references and free-text comments excluded from aggregate exports"]}


from app.admin import router as admin_router
app.include_router(admin_router)
from app.operations import router as operations_router
from app.interop import router as interop_router
app.include_router(operations_router)
app.include_router(interop_router)
from app.baseline import router as baseline_router
app.include_router(baseline_router)
from app.patients import router as patient_workspace_router
from app.resources import router as resource_router
from app.operational_prediction import router as operational_prediction_router
from app.experiments import router as experiments_router
app.include_router(patient_workspace_router)
app.include_router(resource_router)
app.include_router(operational_prediction_router)
app.include_router(experiments_router)
from app.research_workbench import router as research_workbench_router
app.include_router(research_workbench_router)
from app.clinic import router as clinic_router
app.include_router(clinic_router)

from app.schemas import Reassessment


@app.post("/api/v1/visits/{visit_id}/reassess")
def reassess_visit(visit_id: uuid.UUID, payload: Reassessment,
    user: User = Depends(require_roles("CLINICIAN", "TRIAGE_NURSE")), db: Session = Depends(get_db, scope="function"), key: str = Header(alias="Idempotency-Key")):
    visit = require_visit(db, visit_id, user.facility_id)
    if visit.version != payload.version or visit.status not in {"ACTIVE", "ESCALATION_REQUIRED"}:
        raise HTTPException(409, "Refresh the active or escalated visit before reassessment")
    active = [ep for ep in visit.episodes if ep.status in {"WAITING", "CALLED", "IN_SERVICE", "PAUSED"}]
    if any(ep.status != "WAITING" for ep in active):
        raise HTTPException(409, "A reserved or in-service encounter cannot be reranked")
    if payload.action == "RESOLVE_ESCALATION" and visit.status != "ESCALATION_REQUIRED":
        raise HTTPException(409, "Visit does not require escalation resolution")
    if visit.status == "ESCALATION_REQUIRED" and payload.action != "RESOLVE_ESCALATION":
        raise HTTPException(409, "Explicit clinician resolution is required to return to routine queues")
    previous = latest_urgency(db, visit.id)
    db.add(TriageAssessment(facility_id=user.facility_id, visit_id=visit.id, assessor_id=user.id,
        configured_urgency=payload.configured_urgency, reason=payload.reason))
    db.add(ClinicianDecision(facility_id=user.facility_id, visit_id=visit.id, clinician_id=user.id,
        decision="NO_MODEL", final_urgency=payload.configured_urgency, justification=payload.reason))
    visit.status = "ESCALATION_REQUIRED" if payload.action == "ESCALATE" else "ACTIVE"
    visit.version += 1
    for ep in active:
        # Invalidate stale queue buttons while preserving any clinician pin.
        ep.version += 1
        if ep.queue_entry:
            ep.queue_entry.version += 1
    if payload.action == "RESOLVE_ESCALATION" and not active:
        add_episode(db, visit=visit, point_type="consultation", actor_id=user.id)
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="triage.reassessed", object_type="Visit",
        object_id=visit.id, correlation_id=key, old={"urgency": previous},
        new={"urgency": payload.configured_urgency, "status": visit.status}, reason=payload.action,
        metadata={"rationale_hash": hashlib.sha256(payload.reason.encode()).hexdigest()})
    enqueue_event(db, facility_id=user.facility_id, topic="queue.rank_changed", aggregate_id=visit.id,
        version=visit.version, payload={"status": visit.status})
    return {"id": str(visit.id), "status": visit.status, "version": visit.version, "confirmed_urgency": payload.configured_urgency}


@app.post("/api/v1/episodes/{episode_id}/corrections", status_code=201)
def correct_episode(episode_id: uuid.UUID, payload: TimestampCorrection,
    user: User = Depends(require_roles("ADMIN", "CLINICIAN", "TRIAGE_NURSE")), db: Session = Depends(get_db, scope="function"), key: str = Header(alias="Idempotency-Key")):
    episode = require_episode(db, episode_id, user.facility_id)
    if episode.status != "COMPLETED" or episode.version != payload.version:
        raise HTTPException(409, "Only a current completed episode accepts an audited correction")
    latest_correction_id = episode.corrections[-1].id if episode.corrections else None
    if payload.previous_correction_id != latest_correction_id:
        raise HTTPException(409, "A correction was added; refresh the timeline before correcting again")
    allowed = ["queued_at", "called_at", "started_at", "ended_at"]
    if not payload.timestamps or set(payload.timestamps) - set(allowed):
        raise HTTPException(422, "Only episode timestamps may be corrected")
    original = {field: getattr(episode, field).isoformat() if getattr(episode, field) else None for field in allowed}
    corrected = dict(episode.corrections[-1].corrected_values if episode.corrections else original)
    for field, value in payload.timestamps.items():
        if value.tzinfo is None or value > utcnow():
            raise HTTPException(422, "Use timezone-aware timestamps no later than server time")
        corrected[field] = value.isoformat()
    values = [datetime.fromisoformat(corrected[field]).replace(tzinfo=timezone.utc) if datetime.fromisoformat(corrected[field]).tzinfo is None else datetime.fromisoformat(corrected[field]) for field in allowed if corrected[field]]
    arrival = episode.visit.arrival_at
    arrival = arrival.replace(tzinfo=timezone.utc) if arrival.tzinfo is None else arrival
    if values != sorted(values) or values and values[0] < arrival:
        raise HTTPException(422, "Correction violates journey chronology")
    correction = EpisodeCorrection(facility_id=user.facility_id, episode_id=episode.id, actor_id=user.id,
        original_values=original, corrected_values=corrected, reason=payload.reason)
    db.add(correction)
    db.flush()
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action="episode.timestamps_corrected", object_type="EpisodeCorrection",
        object_id=correction.id, correlation_id=key, old=original, new=corrected, reason="Timestamp correction rationale recorded")
    return {"id": str(correction.id), "original": original, "corrected": corrected}

