from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AppointmentStatus, SlotStatus


class SlotCreate(BaseModel):
    doctor_id: int | None = None  # doctor: always self; admin: required
    start_at: datetime
    end_at: datetime


class SlotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    start_at: datetime
    end_at: datetime
    status: SlotStatus


class AppointmentCreate(BaseModel):
    slot_id: int
    case_id: int | None = None
    athlete_id: int | None = None  # registrar/admin book for an athlete; athlete: always self


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slot_id: int
    athlete_id: int
    case_id: int | None
    status: AppointmentStatus
