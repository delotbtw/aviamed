from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, and_, func, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.rbac import Role
from app.models.enums import AppointmentStatus, SlotStatus
from app.models.reference import Specialty
from app.models.schedule import Appointment, Slot
from app.models.user import AthleteProfile, DoctorProfile, User
from app.repositories.base import BaseRepository, domain_errors, violated_constraint
from app.schedule.exceptions import SlotOverlap, SlotTaken

OVERLAP_CONSTRAINT = "ex_slots_no_overlap"
ACTIVE_SLOT_INDEX = "uq_appointments_slot_active"
ACTIVE_APPOINTMENTS = (AppointmentStatus.BOOKED, AppointmentStatus.ARRIVED)
_SLOT_FOR_NO_KEY_UPDATE = {"key_share": True}


class SlotRepository(BaseRepository[Slot]):
    model = Slot

    async def get_locked(self, slot_id: int, *, doctor_id: int | None = None) -> Slot | None:
        """FOR NO KEY UPDATE by id; `doctor_id` restricts the row to one doctor's slots (the foreign one is not read).

        Re-reads the row after the wait (populate_existing), so the caller sees the status committed by the winner.
        """
        stmt = select(Slot).where(Slot.id == slot_id)
        if doctor_id is not None:
            stmt = stmt.where(Slot.doctor_id == doctor_id)
        stmt = stmt.with_for_update(**_SLOT_FOR_NO_KEY_UPDATE).execution_options(populate_existing=True)
        with domain_errors():
            return await self.session.scalar(stmt)

    async def overlapping(self, doctor_id: int, start_at: datetime, end_at: datetime) -> list[Slot]:
        """Slots of the doctor (any status) intersecting [start_at, end_at)."""
        stmt = (
            select(Slot)
            .where(Slot.doctor_id == doctor_id, Slot.start_at < end_at, Slot.end_at > start_at)
            .order_by(Slot.start_at)
        )
        return list(await self.session.scalars(stmt))

    async def free_between(self, start_at: datetime, end_at: datetime) -> list[Slot]:
        """Free slots of all doctors starting in [start_at, end_at), chronologically (demo seed)."""
        stmt = (
            select(Slot)
            .where(Slot.status == SlotStatus.FREE, Slot.start_at >= start_at, Slot.start_at < end_at)
            .order_by(Slot.start_at, Slot.doctor_id, Slot.id)
        )
        return list(await self.session.scalars(stmt))

    async def add_many(self, slots: list[Slot]) -> list[Slot]:
        """Insert the slots; the exclusion constraint has the last word on overlaps (SlotOverlap). Caller rolls back."""
        self.session.add_all(slots)
        try:
            with domain_errors():
                await self.session.flush()
        except IntegrityError as e:
            if violated_constraint(e) != OVERLAP_CONSTRAINT:
                raise
            raise SlotOverlap from None
        return slots


class AppointmentRepository(BaseRepository[Appointment]):
    model = Appointment

    async def add(self, obj: Appointment) -> Appointment:
        """Insert; the partial unique index is the last word on double booking (SlotTaken). The caller rolls back."""
        try:
            return await super().add(obj)
        except IntegrityError as e:
            if violated_constraint(e) != ACTIVE_SLOT_INDEX:
                raise
            raise SlotTaken from None

    async def find(self, appointment_id: int, *, athlete_id: int | None = None) -> Appointment | None:
        """Unlocked read. With `athlete_id` the query itself is restricted to that athlete's rows: a foreign
        appointment is never loaded, so it cannot leak (spec 10)."""
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        if athlete_id is not None:
            stmt = stmt.where(Appointment.athlete_id == athlete_id)
        return await self.session.scalar(stmt)

    async def exists_for_athletes(self, athlete_ids: list[int]) -> bool:
        """Any appointment (any status) of the given athletes (demo seed idempotency)."""
        stmt = select(Appointment.id).where(Appointment.athlete_id.in_(athlete_ids)).limit(1)
        return await self.session.scalar(stmt) is not None

    async def count_active(self, athlete_id: int) -> int:
        stmt = select(func.count()).where(
            Appointment.athlete_id == athlete_id, Appointment.status.in_(ACTIVE_APPOINTMENTS)
        )
        return await self.session.scalar(stmt) or 0

    async def has_active_overlapping(self, athlete_id: int, start_at: datetime, end_at: datetime) -> bool:
        stmt = (
            select(Appointment.id)
            .join(Slot, Slot.id == Appointment.slot_id)
            .where(
                Appointment.athlete_id == athlete_id,
                Appointment.status.in_(ACTIVE_APPOINTMENTS),
                Slot.start_at < end_at,
                Slot.end_at > start_at,
            )
            .limit(1)
        )
        return await self.session.scalar(stmt) is not None


# --------------------------------------------------------------------------- read side (list projections)


@dataclass(frozen=True, slots=True)
class SlotCriteria:
    slot_id: int | None = None
    doctor_id: int | None = None
    specialty_id: int | None = None
    status: SlotStatus | None = None
    starts_after: datetime | None = None  # exclusive
    starts_from: datetime | None = None  # inclusive
    starts_before: datetime | None = None  # exclusive
    starts_until: datetime | None = None  # inclusive


@dataclass(frozen=True, slots=True)
class AppointmentCriteria:
    appointment_id: int | None = None
    athlete_id: int | None = None
    doctor_id: int | None = None
    status: AppointmentStatus | None = None
    starts_from: datetime | None = None  # inclusive
    starts_before: datetime | None = None  # exclusive
    ends_from: datetime | None = None  # inclusive: end_at >= ends_from
    newest_first: bool = False  # history lists; upcoming ones go in chronological order


@dataclass(frozen=True, slots=True)
class AthleteMatch:
    id: int
    last_name: str
    first_name: str
    middle_name: str | None
    birth_date: date


class ScheduleReadRepository:
    """Joined projections for the lists. Rows are plain `Row` objects with labelled columns; no business rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _slot_columns(doctor: Any) -> list[Any]:
        return [
            Slot.id,
            Slot.doctor_id,
            Slot.start_at,
            Slot.end_at,
            Slot.status,
            doctor.last_name.label("doctor_last_name"),
            doctor.first_name.label("doctor_first_name"),
            doctor.middle_name.label("doctor_middle_name"),
            doctor.is_active.label("doctor_active"),
            Specialty.name.label("specialty"),
            DoctorProfile.cabinet,
        ]

    @staticmethod
    def _filter_slots(stmt: Select, c: SlotCriteria) -> Select:
        if c.slot_id is not None:
            stmt = stmt.where(Slot.id == c.slot_id)
        if c.doctor_id is not None:
            stmt = stmt.where(Slot.doctor_id == c.doctor_id)
        if c.specialty_id is not None:
            stmt = stmt.where(DoctorProfile.specialty_id == c.specialty_id)
        if c.status is not None:
            stmt = stmt.where(Slot.status == c.status)
        if c.starts_after is not None:
            stmt = stmt.where(Slot.start_at > c.starts_after)
        if c.starts_from is not None:
            stmt = stmt.where(Slot.start_at >= c.starts_from)
        if c.starts_before is not None:
            stmt = stmt.where(Slot.start_at < c.starts_before)
        if c.starts_until is not None:
            stmt = stmt.where(Slot.start_at <= c.starts_until)
        return stmt

    async def free_slots(self, c: SlotCriteria, *, limit: int, offset: int) -> list[Any]:
        """Single read path of the free-slot list (a cache would sit behind this method, spec 8)."""
        doctor = aliased(User)
        stmt = (
            select(*self._slot_columns(doctor))
            .join(doctor, doctor.id == Slot.doctor_id)
            .join(DoctorProfile, DoctorProfile.user_id == Slot.doctor_id)
            .join(Specialty, Specialty.id == DoctorProfile.specialty_id)
            # Rendered as a literal so that the planner can match the partial index ix_slots_free_start_at.
            .where(Slot.status == literal(SlotStatus.FREE.value, literal_execute=True), doctor.is_active.is_(True))
        )
        stmt = self._filter_slots(stmt, c).order_by(Slot.start_at, Slot.id).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).all())

    async def managed_slots(self, c: SlotCriteria, *, limit: int, offset: int) -> list[Any]:
        """Slots of any status with the active appointment (if any) and the athlete's name."""
        doctor, athlete = aliased(User), aliased(User)
        stmt = (
            select(
                *self._slot_columns(doctor),
                Appointment.id.label("appointment_id"),
                Appointment.status.label("appointment_status"),
                athlete.last_name.label("athlete_last_name"),
                athlete.first_name.label("athlete_first_name"),
                athlete.middle_name.label("athlete_middle_name"),
            )
            .join(doctor, doctor.id == Slot.doctor_id)
            .join(DoctorProfile, DoctorProfile.user_id == Slot.doctor_id)
            .join(Specialty, Specialty.id == DoctorProfile.specialty_id)
            .outerjoin(
                Appointment,
                and_(Appointment.slot_id == Slot.id, Appointment.status != AppointmentStatus.CANCELLED),
            )
            .outerjoin(athlete, athlete.id == Appointment.athlete_id)
        )
        stmt = self._filter_slots(stmt, c).order_by(Slot.start_at, Slot.id).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).all())

    async def appointments(self, c: AppointmentCriteria, *, limit: int, offset: int) -> list[Any]:
        doctor, athlete = aliased(User), aliased(User)
        stmt = (
            select(
                Appointment.id,
                Appointment.status,
                Appointment.slot_id,
                Appointment.athlete_id,
                Appointment.case_id,
                Appointment.cancelled_at,
                Slot.start_at,
                Slot.end_at,
                doctor.last_name.label("doctor_last_name"),
                doctor.first_name.label("doctor_first_name"),
                doctor.middle_name.label("doctor_middle_name"),
                doctor.is_active.label("doctor_active"),
                Specialty.name.label("specialty"),
                DoctorProfile.cabinet,
                athlete.last_name.label("athlete_last_name"),
                athlete.first_name.label("athlete_first_name"),
                athlete.middle_name.label("athlete_middle_name"),
            )
            .join(Slot, Slot.id == Appointment.slot_id)
            .join(doctor, doctor.id == Slot.doctor_id)
            .join(DoctorProfile, DoctorProfile.user_id == Slot.doctor_id)
            .join(Specialty, Specialty.id == DoctorProfile.specialty_id)
            .join(athlete, athlete.id == Appointment.athlete_id)
        )
        if c.appointment_id is not None:
            stmt = stmt.where(Appointment.id == c.appointment_id)
        if c.athlete_id is not None:
            stmt = stmt.where(Appointment.athlete_id == c.athlete_id)
        if c.doctor_id is not None:
            stmt = stmt.where(Slot.doctor_id == c.doctor_id)
        if c.status is not None:
            stmt = stmt.where(Appointment.status == c.status)
        if c.starts_from is not None:
            stmt = stmt.where(Slot.start_at >= c.starts_from)
        if c.starts_before is not None:
            stmt = stmt.where(Slot.start_at < c.starts_before)
        if c.ends_from is not None:
            stmt = stmt.where(Slot.end_at >= c.ends_from)
        order = (Slot.start_at.desc(), Appointment.id.desc()) if c.newest_first else (Slot.start_at, Appointment.id)
        stmt = stmt.order_by(*order).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).all())

    async def active_doctors(self) -> list[Any]:
        """Doctors that take appointments, for the filter selects: id, name parts, specialty, cabinet."""
        doctor = aliased(User)
        stmt = (
            select(
                doctor.id,
                doctor.last_name.label("doctor_last_name"),
                doctor.first_name.label("doctor_first_name"),
                doctor.middle_name.label("doctor_middle_name"),
                DoctorProfile.specialty_id,
                Specialty.name.label("specialty"),
                DoctorProfile.cabinet,
            )
            .join(DoctorProfile, DoctorProfile.user_id == doctor.id)
            .join(Specialty, Specialty.id == DoctorProfile.specialty_id)
            .where(doctor.role == Role.DOCTOR, doctor.is_active.is_(True))
            .order_by(doctor.last_name, doctor.first_name, doctor.id)
        )
        return list((await self.session.execute(stmt)).all())

    async def search_athletes(self, surname_prefix: str, limit: int) -> list[AthleteMatch]:
        """Active athletes whose surname starts with the prefix (case-insensitive)."""
        escaped = surname_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = (
            select(User.id, User.last_name, User.first_name, User.middle_name, AthleteProfile.birth_date)
            .join(AthleteProfile, AthleteProfile.user_id == User.id)
            .where(
                User.role == Role.ATHLETE, User.is_active.is_(True), User.last_name.ilike(escaped + "%", escape="\\")
            )
            .order_by(User.last_name, User.first_name, User.id)
            .limit(limit)
        )
        return [AthleteMatch(*row) for row in (await self.session.execute(stmt)).all()]

    async def find_athlete(self, athlete_id: int) -> AthleteMatch | None:
        """One active athlete by id (for showing a chosen name)."""
        stmt = (
            select(User.id, User.last_name, User.first_name, User.middle_name, AthleteProfile.birth_date)
            .join(AthleteProfile, AthleteProfile.user_id == User.id)
            .where(User.id == athlete_id, User.role == Role.ATHLETE, User.is_active.is_(True))
        )
        row = (await self.session.execute(stmt)).first()
        return AthleteMatch(*row) if row else None
