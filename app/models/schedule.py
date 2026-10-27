from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuthorshipMixin, Base, IdMixin, TimestampMixin, UpdatedByMixin, enum_col
from app.models.enums import AppointmentStatus, SlotStatus


class Slot(IdMixin, TimestampMixin, AuthorshipMixin, Base):
    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("doctor_id", "start_at"),)

    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[SlotStatus] = mapped_column(enum_col(SlotStatus, "slot_status"), default=SlotStatus.FREE)


class Appointment(IdMixin, TimestampMixin, UpdatedByMixin, Base):
    __tablename__ = "appointments"

    # unique slot_id: DB-level guard against double booking, even under concurrency.
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id", ondelete="RESTRICT"), unique=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("medical_cases.id", ondelete="RESTRICT"), index=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        enum_col(AppointmentStatus, "appointment_status"), default=AppointmentStatus.BOOKED, index=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
