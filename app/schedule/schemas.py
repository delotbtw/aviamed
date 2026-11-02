from datetime import date, datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.enums import AppointmentStatus, SlotStatus

# Bounds keep every value inside what PostgreSQL integers and the calendar arithmetic can take (else: 500).
Id = Annotated[int, Field(ge=1, le=2**31 - 1)]
QueryDate = Annotated[date, Field(ge=date(2000, 1, 1), le=date(2100, 1, 1))]
Limit = Annotated[int, Field(ge=1, le=200)]
Offset = Annotated[int, Field(ge=0, le=100_000)]
Request = ConfigDict(extra="forbid")


class SlotCreate(BaseModel):
    model_config = Request

    doctor_id: Id | None = None  # admin and registrar: required
    start_at: AwareDatetime
    end_at: AwareDatetime


class SlotBatchCreate(BaseModel):
    model_config = Request

    doctor_id: Id | None = None
    start_at: AwareDatetime
    end_at: AwareDatetime
    slot_minutes: int


class SlotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    start_at: datetime
    end_at: datetime
    status: SlotStatus


class SlotListItem(BaseModel):
    id: int
    doctor_id: int
    doctor_name: str
    specialty: str
    cabinet: str | None
    start_at: datetime
    end_at: datetime
    status: SlotStatus


class SlotAppointment(BaseModel):
    id: int
    status: AppointmentStatus
    athlete_name: str


class SlotManageItem(SlotListItem):
    appointment: SlotAppointment | None


class AppointmentCreate(BaseModel):
    model_config = Request

    slot_id: Id
    case_id: Id | None = None
    athlete_id: Id | None = None  # registrar/admin book for an athlete; athlete: always self


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slot_id: int
    athlete_id: int
    case_id: int | None
    status: AppointmentStatus


class AppointmentListItem(BaseModel):
    id: int
    status: AppointmentStatus
    slot_id: int
    start_at: datetime
    end_at: datetime
    doctor_name: str
    specialty: str
    cabinet: str | None
    athlete_id: int
    athlete_name: str
    case_id: int | None
    cancelled_at: datetime | None
    doctor_active: bool


class FreeSlotsQuery(BaseModel):
    """Filters of the free-slot list; dates are calendar days in the schedule time zone."""

    model_config = Request

    doctor_id: Id | None = None
    specialty_id: Id | None = None
    date_from: QueryDate | None = None
    date_to: QueryDate | None = None
    limit: Limit = 50
    offset: Offset = 0


class ManagedSlotsQuery(BaseModel):
    model_config = Request

    doctor_id: Id | None = None
    status: SlotStatus | None = None
    date_from: QueryDate | None = None
    date_to: QueryDate | None = None
    limit: Limit = 50
    offset: Offset = 0


class AppointmentsQuery(BaseModel):
    model_config = Request

    athlete_id: Id | None = None
    doctor_id: Id | None = None
    status: AppointmentStatus | None = None
    date_from: QueryDate | None = None
    date_to: QueryDate | None = None
    limit: Limit = 50
    offset: Offset = 0
