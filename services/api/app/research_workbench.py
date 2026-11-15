"""Isolated synthetic research: frozen protocols, blinded references and trials.

These records are not patient visits and cannot mutate a clinical queue. A human
participant must explicitly consent and submit every assessment. Seeded automated
verification responses must be described as fixtures, never fieldwork.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field, field_validator, model_validator
from sklearn.metrics import cohen_kappa_score, confusion_matrix
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commands import CommandRoute
from app.config import settings
from app.database import get_db
from app.ml.pipeline import FEATURES, LABELS, CATEGORIES, validate_frame, advisory_for_display
from app.ml.reliability import probability_diagnostics
from app.models import (CaseAdjudication, CaseReview, Dataset, Job, ModelVersion,
                        ResearchCase, ResearchProtocol, ResearchStudyRun, ResearchTrial, utcnow)
from app.schemas import APIModel
from app.security import require_roles, role_names, rate_limiter
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/research/workbench", route_class=CommandRoute)
DB = Depends(get_db, scope="function")
READ = Depends(require_roles("ADMIN", "RESEARCHER", "CLINICIAN", "TRIAGE_NURSE"))
RESEARCH = Depends(require_roles("ADMIN", "RESEARCHER"))
CLINICIAN = Depends(require_roles("CLINICIAN", "TRIAGE_NURSE"))
WARNING = "Synthetic research only — no clinical validation, autonomous decisions or live schedule changes"
PROTOCOL_VERSION = "workbench-protocol-v1"
FEATURE_METADATA = {
    "age_band": {"unit": "category", "values": CATEGORIES["age_band"], "available_at": "synthetic intake"},
    "visit_type": {"unit": "category", "values": CATEGORIES["visit_type"], "available_at": "synthetic intake"},
    "arrival_mode": {"unit": "category", "values": CATEGORIES["arrival_mode"], "available_at": "synthetic arrival"},
    "hour": {"unit": "hour 0–23", "available_at": "synthetic arrival"},
    "recorded_measurement": {"unit": "dimensionless", "available_at": "synthetic assessment", "meaning": "Generator input, NOT a vital sign or clinical cutoff"},
    "missingness": "Null remains missing; no normal vital signs are assumed",
    "excluded_predictors": ["urgency", "service_minutes", "post-assessment decisions", "identifiers"],
}


class OperationsStudyConfig(APIModel):
    seed: int = Field(default=2026, ge=0, le=2_000_000_000)
    training_days: int = Field(default=40, ge=28, le=90)
    test_days: int = Field(default=12, ge=4, le=30)
    arrivals_per_day: int = Field(default=50, ge=20, le=150)
    replications: int = Field(default=10, ge=2, le=40)
    shift_strength: float = Field(default=1., ge=0, le=2)
    missing_rate: float = Field(default=0., ge=0, le=.5)


class ProtocolCreate(APIModel):
    name: str = Field(min_length=5, max_length=120)
    question: str = Field(min_length=15, max_length=1000)
    dataset_id: uuid.UUID
    model_id: uuid.UUID | None = None
    design: Literal["MANUAL_ONLY", "COUNTERBALANCED", "SHADOW"] = "MANUAL_ONLY"
    case_count: int = Field(default=24, ge=6, le=100)
    seed: int = Field(default=2026, ge=0, le=2**31-1)
    operations_config: OperationsStudyConfig = Field(default_factory=OperationsStudyConfig)

    @field_validator("name", "question")
    @classmethod
    def meaningful_text(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("Meaningful protocol text is required")
        return value.strip()

    @model_validator(mode="after")
    def advisory_model(self):
        if self.design != "MANUAL_ONLY" and not self.model_id:
            raise ValueError("Advisory and shadow designs require a fixed model version")
        return self


class LabelReview(APIModel):
    label: Literal["P1", "P2", "P3", "P4", "P5"]
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("Explain the independent assessment")
        return value.strip()


class TrialStart(APIModel):
    consent_ref: str = Field(min_length=5, max_length=160)
    consented: Literal[True]

    @field_validator("consent_ref")
    @classmethod
    def meaningful_reference(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("A consent reference is required")
        return value.strip()


class TrialComplete(LabelReview):
    understands_authority: bool
    trust_rating: int = Field(ge=1, le=5)


class ProtocolResponse(APIModel):
    id: uuid.UUID
    name: str
    question: str
    dataset_id: uuid.UUID
    model_id: uuid.UUID | None
    design: str
    config_hash: str
    created_at: datetime
    case_count: int
    operations_config: OperationsStudyConfig
    configuration: dict[str, Any]


class CaseResponse(APIModel):
    id: uuid.UUID
    ordinal: int
    features: dict[str, Any]
    review_count: int
    own_review: dict[str, str] | None
    adjudicated: bool


class TrialResponse(APIModel):
    id: uuid.UUID
    case_id: uuid.UUID
    ordinal: int
    features: dict[str, Any]
    arm: str
    status: str
    advisory: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
    final_label: str | None
    elapsed_seconds: float | None
    warning: str


class StudyRunResponse(APIModel):
    id: uuid.UUID
    protocol_id: uuid.UUID
    status: str
    created_at: datetime
    results: dict[str, Any]
    error: str | None


class WorkbenchOverview(APIModel):
    datasets: list[dict[str, Any]]
    models: list[dict[str, Any]]
    protocols: list[ProtocolResponse]
    feature_schema: dict[str, Any]
    warning: str


class ProtocolDetail(APIModel):
    protocol: ProtocolResponse
    cases: list[CaseResponse]
    summary: dict[str, Any]
    trials: list[TrialResponse]
    runs: list[StudyRunResponse]


class ResearchReceipt(APIModel):
    id: uuid.UUID
    recorded: bool
    label_source: str


class AdjudicationResponse(APIModel):
    features: dict[str, Any]
    reviews: list[dict[str, str]]
    adjudication: dict[str, str] | None
    warning: str


class ResearchRunRequest(APIModel):
    pass


class ResearchRunQueued(APIModel):
    run_id: uuid.UUID
    job_id: uuid.UUID
    status: str


class ShadowMonitorResponse(APIModel):
    shadow_completed: int
    missingness: dict[str, float | None]
    categorical_drift: dict[str, Any]
    numeric_drift: dict[str, Any]
    windows: list[dict[str, Any]]
    age_slices: dict[str, Any]
    reference_available: bool
    minimum_drift_samples: int
    automatic_retraining: bool
    automatic_activation: bool
    priority_effect: str
    limitations: list[str]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, default=str).encode()).hexdigest()


def scoped(db, model, object_id, user):
    row = db.scalar(select(model).where(model.id == object_id, model.facility_id == user.facility_id))
    if not row:
        raise HTTPException(404, "Research object not found")
    return row


def audit(db, user, action, obj, key, metadata=None):
    record_audit(db, facility_id=user.facility_id, actor_id=user.id, action=action,
                 object_type=type(obj).__name__, object_id=obj.id, correlation_id=key,
                 new=metadata or {"synthetic": True}, reason="Synthetic research workflow; no patient queue change")


def protocol_view(p):
    return {"id": p.id, "name": p.name, "question": p.question, "dataset_id": p.dataset_id,
            "model_id": p.model_id, "design": p.design, "config_hash": p.config_hash,
            "created_at": p.created_at, "case_count": p.config_json["case_count"],
            "operations_config": p.config_json["operations_config"], "configuration": p.config_json}


def run_view(r):
    return {"id": r.id, "protocol_id": r.protocol_id, "status": r.status,
            "created_at": r.created_at, "results": r.results_json, "error": r.error_summary}


def trial_view(db, trial):
    case = db.get(ResearchCase, trial.case_id)
    advisory = None
    if trial.arm in {"ADVISORY", "EXPLANATION"} or (trial.arm == "SHADOW" and trial.status == "COMPLETED"):
        advisory = (dict(trial.inference_json) if trial.arm == "SHADOW" and trial.status == "COMPLETED"
                    else advisory_for_display(trial.inference_json))
        if trial.arm == "ADVISORY":
            allowed = {"suggestion", "confidence", "abstained", "reasons", "warning", "model_version", "requires_clinician_review"}
            advisory = {k: v for k, v in advisory.items() if k in allowed}
    return {"id": trial.id, "case_id": case.id, "ordinal": case.ordinal, "features": case.features_json,
            "arm": trial.arm, "status": trial.status, "advisory": advisory,
            "started_at": trial.started_at, "completed_at": trial.completed_at,
            "final_label": trial.final_label,
            "elapsed_seconds": (trial.completed_at-trial.started_at).total_seconds() if trial.completed_at else None,
            "warning": WARNING}


def study_summary(db, p):
    cases = db.scalars(select(ResearchCase).where(ResearchCase.protocol_id == p.id)).all()
    case_map = {c.id: c for c in cases}
    reviews = db.scalars(select(CaseReview).where(CaseReview.case_id.in_(case_map)).order_by(CaseReview.created_at, CaseReview.id)).all()
    adjudications = db.scalars(select(CaseAdjudication).where(CaseAdjudication.case_id.in_(case_map))).all()
    by_case = {}
    for review in reviews:
        by_case.setdefault(review.case_id, []).append(review)
    pairs = [rs[:2] for rs in by_case.values() if len(rs) >= 2]
    a = [rs[0].label for rs in pairs]; b = [rs[1].label for rs in pairs]
    kappa = None
    if len(a) >= 2 and len(set(a+b)) > 1:
        value = float(cohen_kappa_score(a, b, labels=LABELS, weights="linear"))
        kappa = value if np.isfinite(value) else None
    refs = {r.case_id: r.label for r in adjudications}
    trials = db.scalars(select(ResearchTrial).where(ResearchTrial.protocol_id == p.id, ResearchTrial.status == "COMPLETED")).all()
    arms = []
    for arm in ["MANUAL", "ADVISORY", "EXPLANATION", "SHADOW"]:
        rows = [t for t in trials if t.arm == arm]
        if not rows:
            continue
        # Keep independently adjudicated and generator reference labels separate.
        subsets = {}
        for source in ["ADJUDICATED_SYNTHETIC", "GENERATOR_SYNTHETIC"]:
            group = [t for t in rows if (t.case_id in refs) == (source == "ADJUDICATED_SYNTHETIC")]
            reference = lambda t: refs.get(t.case_id, case_map[t.case_id].synthetic_label)
            incorrect_advice = [t for t in group if t.inference_json.get("suggestion") and t.inference_json["suggestion"] != reference(t)]
            subsets[source] = {"n": len(group), "agreement": sum(t.final_label == reference(t) for t in group)/len(group) if group else None,
                               "incorrect_suggestions": len(incorrect_advice),
                               "incorrect_suggestions_shown": len(incorrect_advice) if arm in {"ADVISORY", "EXPLANATION"} else 0,
                               "incorrect_suggestions_rejected": sum(t.final_label != t.inference_json["suggestion"] for t in incorrect_advice) if arm in {"ADVISORY", "EXPLANATION"} else None}
        arms.append({"arm": arm, "n": len(rows), "participants": len({t.participant_id for t in rows}),
                     "mean_elapsed_seconds": float(np.mean([(t.completed_at-t.started_at).total_seconds() for t in rows])),
                     "authority_comprehension_rate": sum(t.response_json["understands_authority"] for t in rows)/len(rows),
                     "mean_trust_rating": float(np.mean([t.response_json["trust_rating"] for t in rows])), "references": subsets})
    return {"cases": len(cases), "blind_reviews": len(reviews), "paired_cases": len(pairs), "adjudicated_cases": len(refs),
            "pair_agreement": sum(x == y for x, y in zip(a, b))/len(a) if a else None,
            "linear_weighted_kappa": kappa, "labels": LABELS,
            "pair_confusion_matrix": confusion_matrix(a, b, labels=LABELS).tolist() if a else [[0]*5 for _ in LABELS],
            "completed_trials": len(trials), "participants": len({t.participant_id for t in trials}), "arms": arms,
            "limitations": ["Synthetic-label agreement is not clinical accuracy", "Pooled first-two-reviewer agreement; reviewer pairs may vary",
                            "Weighted kappa treats adjacent neutral labels as ordinal steps, not clinical harm distances",
                            "Descriptive study; participant/case dependence precludes naive independent-row significance tests",
                            "Trust is an unvalidated descriptive rating; elapsed time includes interruptions",
                            "Manual/shadow decisions cannot be counted as rejection of advice that was never shown before the decision",
                            "Reviewers cannot trial cases they labelled or adjudicated; repeated feature snapshots are excluded",
                            "No recruited participants or approved fieldwork are inferred from software fixtures"]}


@router.get("/overview", response_model=WorkbenchOverview)
def overview(user=READ, db: Session=DB):
    datasets = db.scalars(select(Dataset).where(Dataset.facility_id == user.facility_id, Dataset.synthetic_flag.is_(True), Dataset.file_path.is_not(None))).all()
    models = db.scalars(select(ModelVersion).where(ModelVersion.facility_id == user.facility_id).order_by(ModelVersion.created_at.desc())).all()
    protocols = db.scalars(select(ResearchProtocol).where(ResearchProtocol.facility_id == user.facility_id).order_by(ResearchProtocol.created_at.desc())).all()
    return {"datasets": [{"id": str(d.id), "name": d.name, "row_count": d.row_count, "schema": d.schema_json} for d in datasets],
            "models": [{"id": str(m.id), "dataset_id": str(m.dataset_id), "version": m.version, "status": m.status, "metrics": m.metrics_json} for m in models],
            "protocols": [protocol_view(p) for p in protocols], "feature_schema": FEATURE_METADATA, "warning": WARNING}


@router.post("/protocols", response_model=ProtocolResponse, status_code=201)
def publish_protocol(payload: ProtocolCreate, user=RESEARCH, db: Session=DB, key: str=Header(alias="Idempotency-Key")):
    rate_limiter.check(f"protocol:{user.id}", 8, 300)
    dataset = scoped(db, Dataset, payload.dataset_id, user)
    if not dataset.synthetic_flag or not dataset.file_path or dataset.source_type != "SYNTHETIC":
        raise HTTPException(422, "A registered synthetic training CSV is required")
    model = scoped(db, ModelVersion, payload.model_id, user) if payload.model_id else None
    if model and model.dataset_id != dataset.id:
        raise HTTPException(422, "The frozen model and case dataset must have matching provenance")
    if model and payload.design != "MANUAL_ONLY" and model.status != "REVIEWED":
        raise HTTPException(409, "A clinician-reviewed synthetic model is required for advisory studies")
    try:
        raw = Path(dataset.file_path).read_bytes()
        if len(raw) > settings.max_upload_bytes or hashlib.sha256(raw).hexdigest() != dataset.dataset_hash:
            raise ValueError("Dataset content no longer matches its registered hash")
        frame = pd.read_csv(io.BytesIO(raw)); quality = validate_frame(frame)
        frame = frame.assign(_time=pd.to_datetime(frame.observed_at, utc=True)).sort_values("_time", kind="stable")
        # Match the classifier's tied-timestamp holdout boundary exactly.
        boundary = int(frame._time.searchsorted(frame._time.iloc[int(.8*len(frame))], side="left"))
        pool = frame.iloc[boundary:]
        sample = pool.iloc[np.random.default_rng(payload.seed).permutation(len(pool))]
        cases = []; seen = set()
        for _, row in sample.iterrows():
            features = {f: None if pd.isna(row[f]) else row[f].item() if hasattr(row[f], "item") else row[f] for f in FEATURES}
            case_hash = digest(features)
            if case_hash in seen:
                continue
            seen.add(case_hash); cases.append((features, str(row.urgency), case_hash))
            if len(cases) == payload.case_count:
                break
        if len(cases) < payload.case_count:
            raise ValueError("Insufficient distinct cases in the final chronological 20%; reduce case count or use a larger synthetic dataset")
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc) if not isinstance(exc, OSError) else "Private synthetic dataset unavailable") from exc
    configuration = {"protocol_version": PROTOCOL_VERSION, "seed": payload.seed, "case_count": len(cases),
                     "dataset_hash": dataset.dataset_hash, "label_source": "SYNTHETIC_GENERATOR; independent reviews retained separately",
                     "model_version": model.version if model else None,
                     "model_metrics_hash": digest(model.metrics_json) if model else None,
                     "feature_schema": FEATURE_METADATA, "dataset_quality": quality,
                     "case_selection": "Seeded distinct predictor snapshots from final chronological 20%; no subject identifiers exist in this synthetic schema",
                     "case_hashes": [c[2] for c in cases], "operations_config": payload.operations_config.model_dump(),
                     "primary_project_outcome": "Original Objective 4: sum of completed outpatient journey waiting minutes",
                     "supporting_outcomes": ["synthetic label agreement", "abstention coverage", "explanation comprehension", "consultation wait prediction", "fixed-budget resource planning"],
                     "trial_assignment": "Participant-offset rotating MANUAL/ADVISORY/EXPLANATION on successive unseen cases; SHADOW withholds output until independent assessment",
                     "analysis": "Descriptive participant/case-dependent study; no unplanned significance claim; operations use held-out paired replications",
                     "warning": WARNING}
    protocol = ResearchProtocol(facility_id=user.facility_id, dataset_id=dataset.id,
                                model_id=payload.model_id, actor_id=user.id, name=payload.name,
                                question=payload.question, design=payload.design, config_json=configuration,
                                config_hash=digest({"name": payload.name, "question": payload.question, "design": payload.design, "config": configuration}))
    db.add(protocol); db.flush()
    for i, (features, label, case_hash) in enumerate(cases):
        db.add(ResearchCase(facility_id=user.facility_id, protocol_id=protocol.id, ordinal=i+1,
                            features_json=features, synthetic_label=label, source_row_hash=case_hash))
    audit(db, user, "research.protocol_published", protocol, key, {"config_hash": protocol.config_hash, "case_count": len(cases)})
    return protocol_view(protocol)


@router.get("/protocols/{protocol_id}", response_model=ProtocolDetail)
def protocol_detail(protocol_id: uuid.UUID, user=READ, db: Session=DB):
    p = scoped(db, ResearchProtocol, protocol_id, user)
    cases = db.scalars(select(ResearchCase).where(ResearchCase.protocol_id == p.id).order_by(ResearchCase.ordinal)).all()
    reviews = db.scalars(select(CaseReview).where(CaseReview.case_id.in_([c.id for c in cases]))).all()
    adjudications = set(db.scalars(select(CaseAdjudication.case_id).where(CaseAdjudication.case_id.in_([c.id for c in cases]))))
    items = []
    for case in cases:
        own = next((r for r in reviews if r.case_id == case.id and r.reviewer_id == user.id), None)
        items.append({"id": case.id, "ordinal": case.ordinal, "features": case.features_json,
                      "review_count": sum(r.case_id == case.id for r in reviews),
                      "own_review": {"label": own.label, "reason": own.reason} if own else None,
                      "adjudicated": case.id in adjudications})
    trials = db.scalars(select(ResearchTrial).where(ResearchTrial.protocol_id == p.id, ResearchTrial.participant_id == user.id).order_by(ResearchTrial.started_at.desc())).all()
    runs = db.scalars(select(ResearchStudyRun).where(ResearchStudyRun.protocol_id == p.id).order_by(ResearchStudyRun.created_at.desc())).all()
    summary = study_summary(db, p) if role_names(user) & {"ADMIN", "RESEARCHER"} else {
        "message": "Aggregate reference outcomes are restricted to researchers to protect participant blinding"}
    return {"protocol": protocol_view(p), "cases": items, "summary": summary,
            "trials": [trial_view(db, t) for t in trials], "runs": [run_view(r) for r in runs]}


def previous_exposures(db, user):
    reviewed = db.scalars(select(ResearchCase.source_row_hash).join(CaseReview, CaseReview.case_id == ResearchCase.id).where(CaseReview.reviewer_id == user.id, CaseReview.facility_id == user.facility_id)).all()
    trialled = db.scalars(select(ResearchCase.source_row_hash).join(ResearchTrial, ResearchTrial.case_id == ResearchCase.id).where(ResearchTrial.participant_id == user.id, ResearchTrial.facility_id == user.facility_id)).all()
    return set(reviewed), set(trialled)


@router.post("/cases/{case_id}/reviews", response_model=ResearchReceipt, status_code=201)
def review_case(case_id: uuid.UUID, payload: LabelReview, user=CLINICIAN, db: Session=DB, key: str=Header(alias="Idempotency-Key")):
    case = scoped(db, ResearchCase, case_id, user)
    prior = db.scalars(select(CaseReview).where(CaseReview.case_id == case.id)).all()
    if any(r.reviewer_id == user.id for r in prior):
        raise HTTPException(409, "Your immutable independent review already exists")
    if len(prior) >= 2:
        raise HTTPException(409, "Two independent reviews are complete; an existing reviewer may adjudicate")
    if case.source_row_hash in previous_exposures(db, user)[1]:
        raise HTTPException(409, "A previously trialled case cannot become an independent blinded reference")
    review = CaseReview(facility_id=user.facility_id, case_id=case.id, reviewer_id=user.id,
                        label=payload.label, reason=payload.reason)
    db.add(review); db.flush(); audit(db, user, "research.blind_review_recorded", review, key)
    return {"id": str(review.id), "recorded": True, "label_source": "Independent review of a synthetic case"}


def adjudication_access(db, user, case):
    reviews = db.scalars(select(CaseReview).where(CaseReview.case_id == case.id).order_by(CaseReview.created_at, CaseReview.id)).all()
    if len(reviews) < 2:
        raise HTTPException(409, "Two distinct blinded reviewers are required before adjudication")
    if user.id not in {r.reviewer_id for r in reviews}:
        raise HTTPException(403, "Only a reviewer who already submitted a blinded label may inspect the consensus material")
    return reviews


@router.get("/cases/{case_id}/adjudication", response_model=AdjudicationResponse)
def get_adjudication(case_id: uuid.UUID, user=CLINICIAN, db: Session=DB):
    case = scoped(db, ResearchCase, case_id, user); reviews = adjudication_access(db, user, case)
    adjudication = db.scalar(select(CaseAdjudication).where(CaseAdjudication.case_id == case.id))
    return {"features": case.features_json, "reviews": [{"label": r.label, "reason": r.reason} for r in reviews],
            "adjudication": {"label": adjudication.label, "reason": adjudication.reason} if adjudication else None,
            "warning": "Two-reviewer consensus, not an independent third-rater clinical gold standard"}


@router.post("/cases/{case_id}/adjudication", response_model=ResearchReceipt, status_code=201)
def adjudicate(case_id: uuid.UUID, payload: LabelReview, user=CLINICIAN, db: Session=DB, key: str=Header(alias="Idempotency-Key")):
    case = scoped(db, ResearchCase, case_id, user); adjudication_access(db, user, case)
    if db.scalar(select(CaseAdjudication.id).where(CaseAdjudication.case_id == case.id)):
        raise HTTPException(409, "The immutable adjudication already exists")
    item = CaseAdjudication(facility_id=user.facility_id, case_id=case.id, actor_id=user.id,
                            label=payload.label, reason=payload.reason)
    db.add(item); db.flush(); audit(db, user, "research.case_adjudicated", item, key)
    return {"id": str(item.id), "recorded": True, "label_source": "ADJUDICATED_SYNTHETIC"}


@router.post("/protocols/{protocol_id}/trials/start", response_model=TrialResponse, status_code=201)
def start_trial(protocol_id: uuid.UUID, payload: TrialStart, user=CLINICIAN, db: Session=DB, key: str=Header(alias="Idempotency-Key")):
    p = scoped(db, ResearchProtocol, protocol_id, user)
    existing = db.scalar(select(ResearchTrial).where(ResearchTrial.protocol_id == p.id, ResearchTrial.participant_id == user.id, ResearchTrial.status == "STARTED"))
    if existing:
        return trial_view(db, existing)
    reviewed, trialled = previous_exposures(db, user)
    cases = db.scalars(select(ResearchCase).where(ResearchCase.protocol_id == p.id).order_by(ResearchCase.ordinal)).all()
    case = next((c for c in cases if c.source_row_hash not in reviewed | trialled), None)
    if not case:
        raise HTTPException(409, "No unseen, unreviewed cases remain for this participant")
    previous = db.scalars(select(ResearchTrial.id).where(ResearchTrial.protocol_id == p.id, ResearchTrial.participant_id == user.id)).all()
    offset = int(hashlib.sha256(str(user.id).encode()).hexdigest()[:8], 16) % 3
    arm = "MANUAL" if p.design == "MANUAL_ONLY" else "SHADOW" if p.design == "SHADOW" else ["MANUAL", "ADVISORY", "EXPLANATION"][(len(previous)+offset) % 3]
    inference = {}
    if p.model_id and arm != "MANUAL":
        model = scoped(db, ModelVersion, p.model_id, user)
        if model.status != "REVIEWED":
            raise HTTPException(409, "This protocol's model is not currently reviewed; publish a new protocol or restore review through the existing lifecycle")
        try:
            from app.ml.pipeline import evaluate_shadow
            inference = {**evaluate_shadow(model.artifact_path, case.features_json), "model_version": model.version}
        except (OSError, ValueError):
            raise HTTPException(409, "Private research model unavailable; no trial started")
    trial = ResearchTrial(facility_id=user.facility_id, protocol_id=p.id, case_id=case.id,
                          participant_id=user.id, arm=arm, consent_ref=payload.consent_ref,
                          inference_json=inference)
    db.add(trial); db.flush(); audit(db, user, "research.trial_started", trial, key, {"arm": arm, "protocol_hash": p.config_hash})
    return trial_view(db, trial)


@router.post("/trials/{trial_id}/complete", response_model=TrialResponse)
def complete_trial(trial_id: uuid.UUID, payload: TrialComplete, user=CLINICIAN, db: Session=DB, key: str=Header(alias="Idempotency-Key")):
    trial = scoped(db, ResearchTrial, trial_id, user)
    if trial.participant_id != user.id:
        raise HTTPException(404, "Research trial not found")
    if trial.status != "STARTED":
        raise HTTPException(409, "This completed response is immutable")
    trial.final_label = payload.label
    trial.response_json = {"reason": payload.reason, "understands_authority": payload.understands_authority,
                           "trust_rating": payload.trust_rating, "reference_status": "Independent assessment before shadow reveal" if trial.arm == "SHADOW" else "Study response, not an automatic training label"}
    trial.completed_at = utcnow(); trial.status = "COMPLETED"
    db.flush(); audit(db, user, "research.trial_completed", trial, key, {"arm": trial.arm})
    return trial_view(db, trial)


@router.post("/protocols/{protocol_id}/operations", response_model=ResearchRunQueued, status_code=202)
def launch_operations(protocol_id: uuid.UUID, payload: ResearchRunRequest, user=RESEARCH, db: Session=DB, key: str=Header(alias="Idempotency-Key")):
    p = scoped(db, ResearchProtocol, protocol_id, user)
    rate_limiter.check(f"operations-study:{user.id}", 3, 300)
    pending = db.scalar(select(ResearchStudyRun.id).where(ResearchStudyRun.protocol_id == p.id, ResearchStudyRun.status.in_(["PENDING", "RUNNING"])))
    if pending:
        raise HTTPException(409, "This protocol already has a pending supporting study")
    run = ResearchStudyRun(facility_id=user.facility_id, protocol_id=p.id)
    db.add(run); db.flush()
    job = Job(facility_id=user.facility_id, type="RESEARCH_OPERATIONS", result_ref=str(run.id),
              config_json={"protocol_hash": p.config_hash, "operations_config": p.config_json["operations_config"]})
    db.add(job); db.flush(); audit(db, user, "research.operations_queued", run, key, {"protocol_hash": p.config_hash})
    return {"run_id": str(run.id), "job_id": str(job.id), "status": "PENDING"}


@router.get("/runs/{run_id}", response_model=StudyRunResponse)
def get_run(run_id: uuid.UUID, user=READ, db: Session=DB):
    return run_view(scoped(db, ResearchStudyRun, run_id, user))


def monitor_report(db, p):
    trials = db.scalars(select(ResearchTrial).where(ResearchTrial.protocol_id == p.id, ResearchTrial.arm == "SHADOW", ResearchTrial.status == "COMPLETED").order_by(ResearchTrial.completed_at, ResearchTrial.id)).all()
    cases = {c.id: c for c in db.scalars(select(ResearchCase).where(ResearchCase.protocol_id == p.id))}
    rows = [cases[t.case_id].features_json for t in trials]
    reference = None
    if p.model_id:
        model = db.get(ModelVersion, p.model_id)
        try:
            reference = joblib.load(model.artifact_path).get("reference_profile")
        except (OSError, ValueError):
            pass
    n = len(trials); missing = {f: sum(r.get(f) is None for r in rows)/n if n else None for f in FEATURES}
    drift = {}; numeric_drift = {}
    if n >= 10 and reference:
        for f in CATEGORIES:
            missing_fraction = reference.get("missingness", {}).get(f, 0.)
            base = {k: v * (1-missing_fraction) for k, v in reference.get("categorical_frequencies", {}).get(f, {}).items()}
            base["None"] = missing_fraction
            observed = {str(k): sum(str(r.get(f)) == str(k) for r in rows)/n for k in set(base) | {str(r.get(f)) for r in rows}}
            drift[f] = {"total_variation": float(.5*sum(abs(observed[k]-base.get(k, 0)) for k in observed)), "observed": observed, "reference": base}
        for f in ["hour", "recorded_measurement"]:
            values = [float(r[f]) for r in rows if r.get(f) is not None]
            baseline = reference.get("numeric_mean_std", {}).get(f, {})
            if values and baseline.get("std", 0) > 0:
                numeric_drift[f] = {"observed_n": len(values), "observed_mean": float(np.mean(values)),
                                    "fit_mean": baseline["mean"],
                                    "mean_shift_in_fit_standard_deviations": float((np.mean(values)-baseline["mean"])/baseline["std"])}
    windows = []
    # Non-overlapping blocks; do not advertise significance from repeated looks.
    for start in range(0, n, 10):
        group = trials[start:start+10]
        predictions = [t for t in group if t.inference_json.get("predicted_label")]
        advised = [t for t in group if t.inference_json.get("suggestion")]
        labelled = [t for t in group if t.inference_json.get("probabilities")]
        diagnostics = probability_diagnostics([t.final_label for t in labelled],
            [[t.inference_json["probabilities"][label] for label in LABELS] for t in labelled], LABELS) if labelled else None
        windows.append({"start_index": start, "n": len(group), "suggestion_coverage": len(advised)/len(group),
                        "agreement_with_pre_reveal_assessment": sum(t.inference_json["suggestion"] == t.final_label for t in advised)/len(advised) if advised else None,
                        "raw_prediction_agreement": sum(t.inference_json["predicted_label"] == t.final_label for t in predictions)/len(predictions) if predictions else None,
                        "probability_agreement_diagnostics": diagnostics})
    slices = {}
    for band in CATEGORIES["age_band"]:
        group = [t for t in trials if cases[t.case_id].features_json.get("age_band") == band]
        slices[band] = {"n": len(group), "suppressed": len(group) < 30}
        if len(group) >= 30:
            shown = [t for t in group if t.inference_json.get("suggestion")]
            slices[band].update({"suggestion_coverage": len(shown)/len(group),
                                 "agreement_with_pre_reveal_assessment": sum(t.inference_json["suggestion"] == t.final_label for t in shown)/len(shown) if shown else None})
    return {"shadow_completed": n, "missingness": missing, "categorical_drift": drift, "numeric_drift": numeric_drift, "windows": windows,
            "age_slices": slices, "reference_available": bool(reference), "minimum_drift_samples": 10,
            "automatic_retraining": False, "automatic_activation": False, "priority_effect": "NONE",
            "limitations": ["Distribution change is not proof of performance deterioration", "Pre-reveal clinician assessments are comparison labels, not clinical ground truth",
                            "Shadow case mix is synthetic and selected, not a representative clinic sample", "No alarm threshold or statistical significance is claimed",
                            "Age-band performance suppressed below 30; no demographic fairness certification"]}


@router.get("/protocols/{protocol_id}/monitor", response_model=ShadowMonitorResponse)
def monitor(protocol_id: uuid.UUID, user=RESEARCH, db: Session=DB):
    return monitor_report(db, scoped(db, ResearchProtocol, protocol_id, user))


def export_response(payload, filename, format):
    if format == "json":
        content = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False, default=str)
        media_type = "application/json"
    else:
        buffer = io.StringIO(); writer = csv.writer(buffer); writer.writerow(["metric_path", "value_json"])
        def write(value, prefix=""):
            if isinstance(value, dict):
                for key, item in value.items():
                    write(item, f"{prefix}.{key}" if prefix else str(key))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    write(item, f"{prefix}[{i}]")
            else:
                # JSON encoding prevents string values from becoming spreadsheet formulas.
                writer.writerow([prefix, json.dumps(value, allow_nan=False, default=str)])
        write(payload); content = buffer.getvalue(); media_type = "text/csv"
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}.{format}"', "Cache-Control": "no-store"})


@router.get("/protocols/{protocol_id}/export")
def export_protocol(protocol_id: uuid.UUID, format: Literal["json", "csv"]=Query("json"), user=RESEARCH, db: Session=DB):
    p = scoped(db, ResearchProtocol, protocol_id, user)
    payload = {"protocol": protocol_view(p), "summary": study_summary(db, p), "monitor": monitor_report(db, p),
               "warning": WARNING, "privacy": "No participant identifiers, consent references, comments or individual case labels exported"}
    return export_response(payload, f"hutano-protocol-{p.id}", format)


@router.get("/runs/{run_id}/export")
def export_run(run_id: uuid.UUID, format: Literal["json", "csv"]=Query("json"), user=RESEARCH, db: Session=DB):
    run = scoped(db, ResearchStudyRun, run_id, user)
    if run.status != "COMPLETED":
        raise HTTPException(409, "Supporting research results are not completed")
    p = scoped(db, ResearchProtocol, run.protocol_id, user)
    return export_response({"protocol_hash": p.config_hash, "run_id": str(run.id), "warning": WARNING, "results": run.results_json}, f"hutano-study-{run.id}", format)
