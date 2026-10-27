from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import CaseStatus


class CaseCreate(BaseModel):
    athlete_id: int
    program_id: int


class CaseRead(BaseModel):
    """Status view only: no medical details (coach and registrar see this)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    athlete_id: int
    program_id: int
    status: CaseStatus
    opened_at: datetime
    closed_at: datetime | None
    valid_until: date | None
