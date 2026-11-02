"""Read side of the schedule: free slots, the doctor's slot table, appointment lists, small directories.

No locks and no audit (the lists carry no medical data, spec 9 item 21). Time windows are resolved to UTC here.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.core.clock import Clock
from app.core.config import Settings
from app.core.exceptions import InvalidInput, PermissionDenied
from app.core.local_time import LocalCalendar
from app.core.names import full_name
from app.core.rbac import Role
from app.models.enums import AppointmentStatus
from app.models.user import User
from app.repositories.schedule import AppointmentCriteria, ScheduleReadRepository, SlotCriteria
from app.schedule.access import require_slot_viewer
from app.schedule.schemas import (
    AppointmentListItem,
    AppointmentsQuery,
    FreeSlotsQuery,
    ManagedSlotsQuery,
    SlotAppointment,
    SlotListItem,
    SlotManageItem,
)

DATES_REVERSED = "date_from is later than date_to"
HISTORY_STATUSES = frozenset({AppointmentStatus.CANCELLED, AppointmentStatus.DONE, AppointmentStatus.NO_SHOW})
ATHLETE_SEARCH_MIN_CHARS = 2
ATHLETE_SEARCH_LIMIT = 10


@dataclass(frozen=True, slots=True)
class DoctorOption:
    id: int
    name: str
    specialty_id: int
    specialty: str
    cabinet: str | None


@dataclass(frozen=True, slots=True)
class AthleteOption:
    id: int
    name: str
    birth_date: date


def _doctor_name(row: Any) -> str:
    return full_name(row.doctor_last_name, row.doctor_first_name, row.doctor_middle_name)


def _athlete_name(row: Any) -> str:
    return full_name(row.athlete_last_name, row.athlete_first_name, row.athlete_middle_name)


def _slot_item(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "doctor_id": row.doctor_id,
        "doctor_name": _doctor_name(row),
        "specialty": row.specialty,
        "cabinet": row.cabinet,
        "start_at": row.start_at,
        "end_at": row.end_at,
        "status": row.status,
    }


class ScheduleQueryService:
    def __init__(
        self, reader: ScheduleReadRepository, clock: Clock, calendar: LocalCalendar, settings: Settings
    ) -> None:
        self.reader = reader
        self.clock = clock
        self.calendar = calendar
        self.settings = settings

    async def free_slots(self, q: FreeSlotsQuery) -> list[SlotListItem]:
        """Free future slots inside the horizon of active doctors, ordered by start time."""
        now = self.clock.now()
        first = q.date_from or self.calendar.day_of(now)
        last = q.date_to or self.calendar.day_of(now + timedelta(days=self.settings.schedule_horizon_days))
        self._check_order(first, last)
        criteria = SlotCriteria(
            doctor_id=q.doctor_id,
            specialty_id=q.specialty_id,
            starts_after=now,
            starts_from=self.calendar.day_start(first),
            starts_before=self.calendar.next_day_start(last),
            starts_until=now + timedelta(days=self.settings.schedule_horizon_days),
        )
        rows = await self.reader.free_slots(criteria, limit=q.limit, offset=q.offset)
        return [SlotListItem(**_slot_item(r)) for r in rows]

    async def managed_slots(self, q: ManagedSlotsQuery, actor: User) -> list[SlotManageItem]:
        """Slots of any status for the doctor (own only) or admin (all, optionally one doctor)."""
        require_slot_viewer(actor)
        doctor_id = self._doctor_scope(actor, q.doctor_id)
        criteria = SlotCriteria(doctor_id=doctor_id, status=q.status, **self._day_window(q.date_from, q.date_to))
        rows = await self.reader.managed_slots(criteria, limit=q.limit, offset=q.offset)
        return [self._manage_item(r) for r in rows]

    async def managed_slot(self, slot_id: int, actor: User) -> SlotManageItem | None:
        """One row of the management table (for fragments), with the same visibility rules."""
        require_slot_viewer(actor)
        criteria = SlotCriteria(slot_id=slot_id, doctor_id=self._doctor_scope(actor, None))
        rows = await self.reader.managed_slots(criteria, limit=1, offset=0)
        return self._manage_item(rows[0]) if rows else None

    async def appointments(self, q: AppointmentsQuery, actor: User) -> list[AppointmentListItem]:
        """Athlete: only own. Staff: all, filtered. Without dates and status only appointments not yet over."""
        athlete_id = q.athlete_id
        if actor.role is Role.ATHLETE:
            if athlete_id not in (None, actor.id):
                raise PermissionDenied("Athletes see only their own appointments")
            athlete_id = actor.id
        window = self._day_window(q.date_from, q.date_to)
        ends_from = self.clock.now() if not window and q.status is None else None
        criteria = AppointmentCriteria(
            athlete_id=athlete_id,
            doctor_id=q.doctor_id,
            status=q.status,
            starts_from=window.get("starts_from"),
            starts_before=window.get("starts_before"),
            ends_from=ends_from,
            newest_first=q.status in HISTORY_STATUSES,  # history: latest first; upcoming and daily queues: by time
        )
        rows = await self.reader.appointments(criteria, limit=q.limit, offset=q.offset)
        return [self._appointment_item(r) for r in rows]

    async def appointment(self, appointment_id: int, actor: User) -> AppointmentListItem | None:
        """One appointment (for row fragments); an athlete gets only own, the query is restricted by `athlete_id`."""
        own = actor.id if actor.role is Role.ATHLETE else None
        rows = await self.reader.appointments(
            AppointmentCriteria(appointment_id=appointment_id, athlete_id=own), limit=1, offset=0
        )
        return self._appointment_item(rows[0]) if rows else None

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _check_order(first: date, last: date) -> None:
        if first > last:
            raise InvalidInput(DATES_REVERSED)

    @staticmethod
    def _doctor_scope(actor: User, requested: int | None) -> int | None:
        if actor.role is Role.DOCTOR:
            return actor.id  # a foreign doctor_id is ignored, not refused: it must reveal nothing
        return requested

    def _day_window(self, date_from: date | None, date_to: date | None) -> dict[str, datetime]:
        """Calendar days of the schedule time zone, `date_to` inclusive, as UTC bounds."""
        if date_from is not None and date_to is not None:
            self._check_order(date_from, date_to)
        window: dict[str, datetime] = {}
        if date_from is not None:
            window["starts_from"] = self.calendar.day_start(date_from)
        if date_to is not None:
            window["starts_before"] = self.calendar.next_day_start(date_to)
        return window

    @staticmethod
    def _manage_item(row: Any) -> SlotManageItem:
        appointment = None
        if row.appointment_id is not None:
            appointment = SlotAppointment(
                id=row.appointment_id, status=row.appointment_status, athlete_name=_athlete_name(row)
            )
        return SlotManageItem(**_slot_item(row), appointment=appointment)

    @staticmethod
    def _appointment_item(row: Any) -> AppointmentListItem:
        return AppointmentListItem(
            id=row.id,
            status=row.status,
            slot_id=row.slot_id,
            start_at=row.start_at,
            end_at=row.end_at,
            doctor_name=_doctor_name(row),
            specialty=row.specialty,
            cabinet=row.cabinet,
            athlete_id=row.athlete_id,
            athlete_name=_athlete_name(row),
            case_id=row.case_id,
            cancelled_at=row.cancelled_at,
            doctor_active=row.doctor_active,
        )


class ScheduleDirectory:
    """Small lookups for the page filters and the registrar's athlete search."""

    def __init__(self, reader: ScheduleReadRepository) -> None:
        self.reader = reader

    async def doctors(self) -> list[DoctorOption]:
        return [
            DoctorOption(r.id, _doctor_name(r), r.specialty_id, r.specialty, r.cabinet)
            for r in await self.reader.active_doctors()
        ]

    async def find_athletes(self, surname_prefix: str) -> list[AthleteOption]:
        """Active athletes by the start of the surname; shorter than 2 characters gives nothing."""
        prefix = surname_prefix.strip()
        if len(prefix) < ATHLETE_SEARCH_MIN_CHARS:
            return []
        found = await self.reader.search_athletes(prefix, ATHLETE_SEARCH_LIMIT)
        return [AthleteOption(a.id, full_name(a.last_name, a.first_name, a.middle_name), a.birth_date) for a in found]

    async def athlete(self, athlete_id: int, actor: User) -> str | None:
        """Full name of an active athlete for the staff who look athletes up; nobody else gets a name."""
        if actor.role not in (Role.ADMIN, Role.REGISTRAR):
            return None
        found = await self.reader.find_athlete(athlete_id)
        return full_name(found.last_name, found.first_name, found.middle_name) if found else None
