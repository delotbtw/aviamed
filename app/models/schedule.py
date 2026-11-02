from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, literal_column, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuthorshipMixin, Base, IdMixin, TimestampMixin, UpdatedByMixin, enum_col
from app.models.enums import AppointmentStatus, SlotStatus


class Slot(IdMixin, TimestampMixin, AuthorshipMixin, Base):
    __tablename__ = "slots"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="end_after_start"),
        # Slots of one doctor never overlap ([start, end): touching is fine); needs the btree_gist extension.
        # Also implies uniqueness of (doctor_id, start_at): equal starts of positive-length slots overlap.
        ExcludeConstraint(
            ("doctor_id", "="),
            (literal_column("tstzrange(start_at, end_at, '[)')"), "&&"),
            name="ex_slots_no_overlap",
            using="gist",
        ),
        # The free-slot list reads only this slice, ordered by start time.
        Index("ix_slots_free_start_at", "start_at", postgresql_where=text("status = 'free'")),
    )

    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[SlotStatus] = mapped_column(enum_col(SlotStatus, "slot_status"), default=SlotStatus.FREE)


class Appointment(IdMixin, TimestampMixin, UpdatedByMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # DB-level guard against double booking, even under concurrency: one non-cancelled appointment per slot.
        # A cancelled row stays as history and does not block booking the slot again.
        Index(
            "uq_appointments_slot_active",
            "slot_id",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
    )

    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id", ondelete="RESTRICT"))
    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("medical_cases.id", ondelete="RESTRICT"), index=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        enum_col(AppointmentStatus, "appointment_status"), default=AppointmentStatus.BOOKED, index=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
