from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import CaseStatus, Decision


class ConclusionCreate(BaseModel):
    case_id: int
    decision: Decision
    admitted_training: bool = False
    admitted_competitions: bool = False
    admitted_physical_events: bool = False
    admitted_gto: bool = False
    event_name: str | None = None
    sport_discipline: str | None = None
    has_restrictions: bool = False
    restrictions_term: str | None = None
    restrictions: str | None = None


class ConclusionRead(ConclusionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    doctor_id: int
    issued_at: datetime
    valid_until: date


class ClearanceStatus(BaseModel):
    """What coach and registrar may see: status and term, no diagnoses."""

    case_id: int
    case_status: CaseStatus
    decision: Decision | None
    has_restrictions: bool | None
    valid_until: date | None
