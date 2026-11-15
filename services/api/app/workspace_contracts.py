"""Public response contracts for the operational-workspace extension."""
from datetime import datetime
from pydantic import BaseModel, Field
from app.contracts import VisitResponse, PatientSummary


class ObservationFieldResponse(BaseModel):
    code:str
    label:str
    unit:str
    required:bool


class ObservationResponse(BaseModel):
    id:str
    field_code:str
    value:str|None
    unit:str|None
    observed_at:datetime


class NoteResponse(BaseModel):
    id:str
    episode_id:str
    text:str
    at:datetime


class AssessmentResponse(BaseModel):
    urgency:str
    reason:str|None
    at:datetime


class HandoverResponse(BaseModel):
    id:str
    visit_id:str
    source_episode_id:str
    target_point_id:str
    message:str
    acknowledged_at:datetime|None
    version:int
    created_at:datetime


class EncounterResponse(VisitResponse):
    observations:list[ObservationResponse]
    notes:list[NoteResponse]
    assessments:list[AssessmentResponse]
    handovers:list[HandoverResponse]


class WorkspaceResponse(BaseModel):
    patient:PatientSummary
    visits:list[EncounterResponse]
    clinical_details_visible:bool


class RoomResponse(BaseModel):
    id:str
    name:str
    service_point_id:str
    service_type:str
    version:int
    staff_id:str|None
    staff_name:str|None
    available:bool
    staffed:bool
    reasons:list[str]
    shift_id:str|None
    assignment_id:str|None
    episode_id:str|None


class StaffResponse(BaseModel):
    id:str
    name:str
    roles:list[str]


class ScheduleResponse(BaseModel):
    id:str
    room_id:str|None
    staff_id:str|None
    starts_at:datetime
    ends_at:datetime
    cancelled:bool
    version:int
    reason:str|None=None


class UtilisationRoomResponse(BaseModel):
    room:str
    available_minutes:float
    occupied_minutes:float
    utilisation:float|None


class UtilisationResponse(BaseModel):
    from_:datetime=Field(alias='from')
    through:datetime
    rooms:list[UtilisationRoomResponse]
    definition:str
    limitation:str


class BoardResponse(BaseModel):
    rooms:list[RoomResponse]
    staff:list[StaffResponse]
    shifts:list[ScheduleResponse]
    blocks:list[ScheduleResponse]
    history:UtilisationResponse|None


class DurationResponse(BaseModel):
    available:bool
    warning:str
    reason:str|None=None
    minimum_minutes:float|None=None
    median_minutes:float|None=None
    maximum_minutes:float|None=None
    model_version:str|None=None
    dataset_hash:str|None=None
    nominal_coverage:float|None=None
    measured_test_coverage:float|None=None
    priority_effect:str='NONE'


class AlternativeResponse(RoomResponse):
    recent_assignments:int
    room_history_samples:int
    mean_occupied_minutes:float|None
    explanation:str


class ProposalResponse(BaseModel):
    id:str
    options:list[AlternativeResponse]
    recommended_room_id:str|None
    duration_estimate:DurationResponse
    expires_at:datetime
    requires_approval:bool
