from datetime import timedelta

from app.core.clock import Clock
from app.core.config import Settings
from app.core.exceptions import InvalidInput
from app.models.enums import CaseStatus, SlotStatus
from app.models.schedule import Slot
from app.repositories.medical import MedicalCaseRepository
from app.repositories.schedule import AppointmentRepository
from app.repositories.user import UserRepository
from app.schedule.exceptions import (
    ATHLETE_OVERLAP,
    DOCTOR_NOT_ACTIVE,
    SLOT_CLOSED,
    SLOT_STARTED,
    SLOT_TOO_FAR,
    TOO_MANY_ACTIVE,
    AppointmentConflict,
    SlotTaken,
    SlotUnavailable,
)

BOOKABLE_CASE_STATUSES = frozenset({CaseStatus.REGISTERED, CaseStatus.IN_PROGRESS})


class BookingPolicy:
    """What must hold for a booking. Every check reads state, so the caller runs them under its row locks."""

    def __init__(
        self,
        users: UserRepository,
        appointments: AppointmentRepository,
        cases: MedicalCaseRepository,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self.users = users
        self.appointments = appointments
        self.cases = cases
        self.clock = clock
        self.settings = settings

    async def check_slot(self, slot: Slot) -> None:
        now = self.clock.now()
        if slot.status is SlotStatus.BOOKED:
            raise SlotTaken
        if slot.status is SlotStatus.CLOSED:
            raise SlotUnavailable(SLOT_CLOSED)
        if slot.start_at <= now:
            raise SlotUnavailable(SLOT_STARTED)
        if slot.start_at > now + timedelta(days=self.settings.schedule_horizon_days):
            raise SlotUnavailable(SLOT_TOO_FAR)
        if not await self.users.is_active(slot.doctor_id):
            raise SlotUnavailable(DOCTOR_NOT_ACTIVE)

    async def check_case(self, case_id: int, athlete_id: int) -> None:
        """Locks the case row (the last lock in the order) and checks it is an open case of this athlete."""
        case = await self.cases.get_for_update(case_id)
        if case is None or case.athlete_id != athlete_id or case.status not in BOOKABLE_CASE_STATUSES:
            raise InvalidInput("case_id must point at an open case of the athlete")

    async def check_athlete_capacity(self, athlete_id: int, slot: Slot) -> None:
        if await self.appointments.has_active_overlapping(athlete_id, slot.start_at, slot.end_at):
            raise AppointmentConflict(ATHLETE_OVERLAP)
        if await self.appointments.count_active(athlete_id) >= self.settings.max_active_appointments:
            raise AppointmentConflict(TOO_MANY_ACTIVE)
