"""Response schemas are the source of the generated browser contract."""
from datetime import datetime
from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    facility_id: str
    roles: list[str]
    research_mode: bool
    must_change_password: bool = False
    session_idle_minutes: int = 30


class CorrectionResponse(BaseModel):
    id: str
    original: dict[str, str | None]
    corrected: dict[str, str | None]
    created_at: datetime


class EpisodeResponse(BaseModel):
    id: str
    service_point_id: str
    service_point: str
    service_type: str
    sequence_no: int
    status: str
    queued_at: datetime | None = None
    called_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    version: int
    recall_count: int = 0
    missed_calls: int = 0
    deferred_until: datetime | None = None
    corrections: list[CorrectionResponse] = Field(default_factory=list)


class PatientSummary(BaseModel):
    id: str
    pseudonym: str | None = None
    age_band: str | None = None
    sex: str | None = None
    synthetic: bool


class VisitResponse(BaseModel):
    id: str
    public_token: str
    status: str
    visit_type: str
    arrival_at: datetime
    registered_at: datetime | None = None
    completed_at: datetime | None = None
    planned_services: list[str]
    version: int
    synthetic: bool
    entry_mode: str = "LIVE"
    patient: PatientSummary | None = None
    episodes: list[EpisodeResponse]
    opaque_status_token: str | None = None


class ServicePointResponse(BaseModel):
    id: str
    name: str
    type: str
    capacity: int
    active: bool
    outage_state: str
    outage_reason: str | None = None
    version: int
    operating_hours: dict[str,str]
    allowed_routes: list[str]


class QueueEntryResponse(BaseModel):
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
    score_components: dict[str,float]
    requires_clinician_review: bool
    model_suggestion_applied_automatically: bool
    deferred_until: datetime | None = None
    missed_calls: int = 0
    carried_over: bool = False
    overtaken_by: int = 0
    minutes_since_review: int = 0
    review_recommended: bool = False


class QueueResponse(BaseModel):
    service_point_id: str
    generated_at: datetime
    entries: list[QueueEntryResponse]
