import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", allow_inf_nan=False)


class LoginRequest(APIModel):
    email: str = Field(min_length=5, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=8, max_length=128)


class PasswordChange(APIModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PatientCreate(APIModel):
    pseudonym: str | None = Field(default=None, max_length=120)
    year_of_birth: int | None = Field(default=None, ge=1900, le=2200)
    age_band: str | None = Field(default=None, max_length=30)
    sex: str | None = Field(default=None, max_length=30)
    synthetic_flag: bool = True

    @field_validator("synthetic_flag")
    @classmethod
    def synthetic_only(cls, value: bool) -> bool:
        if not value:
            raise ValueError("This research build accepts synthetic patients only")
        return value


class VisitCreate(APIModel):
    patient_id: uuid.UUID
    visit_type: str = Field(default="walk_in", pattern="^[a-z_]{2,40}$")
    planned_services: list[str] = Field(default_factory=lambda: ["triage", "consultation", "pharmacy"])
    arrival_at: datetime | None = None


class RegisterVisit(APIModel):
    version: int = Field(ge=1)


class TriageCreate(APIModel):
    configured_urgency: Literal["P1", "P2", "P3", "P4", "P5"]
    reason: str | None = Field(default=None, max_length=500)
    observations: dict[str, float | int | str | None] = Field(default_factory=dict)
    escalation_required: bool = False
    recommendation_id: uuid.UUID | None = None
    recommendation_decision: Literal["ACCEPT", "REJECT", "OVERRIDE", "NO_MODEL"] = "NO_MODEL"
    version: int = Field(ge=1)

    @field_validator("observations")
    @classmethod
    def bounded_observations(cls, value):
        if len(value) > 30 or any(len(k) > 80 or len(str(v)) > 120 for k,v in value.items()):
            raise ValueError("At most 30 observation fields; codes up to 80 and values up to 120 characters")
        return value


class QueueCall(APIModel):
    version: int = Field(ge=1)


class Reassessment(APIModel):
    version: int = Field(ge=1)
    configured_urgency: Literal["P1", "P2", "P3", "P4", "P5"]
    reason: str = Field(min_length=5, max_length=500)
    action: Literal["REASSESS", "ESCALATE", "RESOLVE_ESCALATION"] = "REASSESS"


class EpisodeStart(APIModel):
    version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=240)


class EpisodeComplete(APIModel):
    version: int = Field(ge=1)
    next_service_type: str | None = Field(default=None, pattern="^[a-z_]{2,40}$")
    operational_note: str | None = Field(default=None, max_length=500)


class EpisodeTransfer(APIModel):
    version: int = Field(ge=1)
    next_service_type: str = Field(pattern="^[a-z_]{2,40}$")
    reason: str = Field(min_length=3, max_length=240)


class EpisodeStateChange(APIModel):
    action: Literal["PAUSE", "NO_SHOW", "CANCEL", "REOPEN_WAITING", "RECALL", "DEFER"]
    version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=240)
    # DEFER only: minutes before a patient who missed their call is callable again.
    defer_minutes: int | None = Field(default=None, ge=1, le=60)


class QueueOverride(APIModel):
    queue_entry_id: uuid.UUID
    new_rank: int = Field(ge=1, le=999)
    reason_code: Literal["CLINICAL_JUDGEMENT", "PATIENT_CHANGED", "OPERATIONAL", "OTHER"]
    note: str | None = Field(default=None, max_length=500)
    version: int = Field(ge=1)
    release: bool = False


class TimestampCorrection(APIModel):
    timestamps: dict[str, datetime]
    reason: str = Field(min_length=5, max_length=240)
    version: int = Field(ge=1)
    previous_correction_id: uuid.UUID | None = None


class AvailabilityUpdate(APIModel):
    capacity: int = Field(ge=0, le=50)
    outage_state: Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE"]
    reason: str | None = Field(default=None, max_length=240)
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def outage_reason_required(self):
        if (self.capacity == 0 or self.outage_state != "AVAILABLE") and not (self.reason and len(self.reason.strip()) >= 3):
            raise ValueError("An operational reason is required for reduced availability")
        return self


class RecommendationDecisionCreate(APIModel):
    decision: Literal["ACCEPT", "REJECT", "OVERRIDE"]
    final_urgency: Literal["P1", "P2", "P3", "P4", "P5"]
    justification: str = Field(min_length=3, max_length=500)


class PatientStatusLookup(APIModel):
    token: str = Field(min_length=20, max_length=200)


class OutageConfig(APIModel):
    stage: Literal["registration", "triage", "consultation", "pharmacy"] = "consultation"
    start_minute: float = Field(ge=0, le=10000)
    duration_minutes: float = Field(gt=0, le=10000)
    available_servers: int = Field(default=0, ge=0, le=20, strict=True)


class ResearchArms(APIModel):
    promote_minutes: float = Field(default=60, ge=5, le=480)
    max_promotion_levels: int = Field(default=2, ge=1, le=4)
    duration_guard_minutes: float = Field(default=60, ge=5, le=480)
    prediction_error_sigma: float = Field(default=.35, ge=0, le=2)


class CalibratedSimulationCreate(APIModel):
    dataset_id: uuid.UUID
    name: str = Field(default="Baseline-calibrated comparison", min_length=3, max_length=120)
    seed: int = Field(default=2026, ge=0, le=2**31 - 1)
    replications: int = Field(default=20, ge=2, le=100)
    include_research_arms: bool = True
    research: ResearchArms | None = None
    urgency_mix: list[float] | None = None
    validation_tolerance: float = Field(default=.25, gt=0, le=1)


class SimulationCreate(APIModel):
    name: str = Field(default="Synthetic outpatient comparison", min_length=3, max_length=120)
    seed: int = Field(default=2026, ge=0, le=2**31 - 1)
    patient_count: int = Field(default=300, ge=0, le=5000)
    replications: int = Field(default=10, ge=1, le=100)
    consultation_servers: int = Field(default=2, ge=0, le=20)
    arrival_rate_per_hour: float = Field(default=24.0, gt=0, le=500)
    mean_service_minutes: float = Field(default=12.0, gt=0, le=240)
    high_load: bool = False
    urgency_mix: list[float] | None = None
    pharmacy_probability: float = Field(default=.75, ge=0, le=1)
    arrival_pattern: Literal["poisson", "burst"] = "poisson"
    hourly_rates: list[float] | None = None
    stage_capacities: dict[str, int] = Field(default_factory=dict)
    stage_means: dict[str, float] = Field(default_factory=dict)
    outage: OutageConfig | None = None
    warning_minutes: float = Field(default=60, gt=0, le=1440)
    service_tail: float = Field(default=.5, ge=0, le=2)
    # Research-only arms (ADR-034): bounded cross-category ageing and duration-aware ordering.
    include_research_arms: bool = False
    research: ResearchArms | None = None

    @model_validator(mode="after")
    def validate_scenario(self):
        if self.patient_count * self.replications > 100000:
            raise ValueError("Limit total simulated patients to 100,000 per experiment")
        if self.urgency_mix is not None and (len(self.urgency_mix) != 5 or any(x < 0 for x in self.urgency_mix) or abs(sum(self.urgency_mix) - 1) > 1e-6):
            raise ValueError("Urgency mix must contain five nonnegative probabilities summing to 1")
        if self.hourly_rates is not None and (not 1 <= len(self.hourly_rates) <= 24 or any(x <= 0 or x > 500 for x in self.hourly_rates)):
            raise ValueError("Hourly rates must contain 1–24 positive rates up to 500/hour")
        for stage, capacity in self.stage_capacities.items():
            if stage not in {"registration", "triage", "pharmacy"} or not 0 <= capacity <= 20:
                raise ValueError("Invalid stage capacity")
        for stage, duration in self.stage_means.items():
            if stage not in {"registration", "triage", "pharmacy"} or not 0 < duration <= 240:
                raise ValueError("Invalid stage duration")
        return self


class ModelTrain(APIModel):
    dataset_id: uuid.UUID | None = None
    seed: int = Field(default=2026, ge=0, le=2**31 - 1)


class ModelReview(APIModel):
    action: Literal["REVIEW", "ACTIVATE", "DISABLE", "RETIRE"]
    reason: str = Field(min_length=5, max_length=500)


class InferenceRequest(APIModel):
    # Optional: by default inputs come from the visit record (ADR-033). `observations` carries
    # vital signs typed into the triage form but not yet saved; `features` is the legacy manual path.
    features: dict[str, float | int | str | None] | None = None
    observations: dict[str, float | None] | None = None



class DatasetMetadata(APIModel):
    name: str = Field(min_length=3, max_length=120)
    source_type: Literal["SYNTHETIC"]
    consent_basis_note: str = Field(min_length=10, max_length=500)
    synthetic_flag: bool = True


class FeedbackCreate(APIModel):
    role_group: str = Field(min_length=2, max_length=60)
    task_id: str = Field(min_length=2, max_length=80)
    consent_ref: str = Field(min_length=3, max_length=100)
    response: dict[str, Any]

    @field_validator("response")
    @classmethod
    def feedback_fields(cls, value):
        allowed = {"completed", "duration_seconds", "errors", "comments", "trust_rating", "explanation_clear", "sus", "tam"}
        if set(value) - allowed:
            raise ValueError("Unexpected feedback field")
        from app.evaluation import validate_sus, validate_tam
        if "sus" in value:
            validate_sus(value["sus"])
        if "tam" in value:
            validate_tam(value["tam"])
        if "completed" in value and not isinstance(value["completed"], bool):
            raise ValueError("completed must be true or false")
        for field in ["duration_seconds", "errors"]:
            if field in value and (not isinstance(value[field], (int, float)) or not 0 <= value[field] <= 86400):
                raise ValueError("Task duration/errors must be non-negative and bounded")
        if "trust_rating" in value and value["trust_rating"] not in [1,2,3,4,5]:
            raise ValueError("Trust rating is a descriptive 1–5 response, not a validated benchmark")
        if len(str(value.get("comments", ""))) > 2000:
            raise ValueError("Comments are limited to 2,000 characters")
        return value

