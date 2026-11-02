from app.audit.service import AuditService
from app.core.clock import Clock
from app.core.config import Settings
from app.core.exceptions import ConcurrentUpdate, NotFound
from app.core.local_time import LocalCalendar
from app.core.uow import UnitOfWork
from app.models.enums import AppointmentStatus, CaseStatus
from app.models.schedule import Appointment, Slot
from app.models.user import User
from app.repositories.medical import MedicalCaseRepository
from app.repositories.schedule import AppointmentRepository, SlotRepository
from app.schedule.exceptions import (
    CASE_CHANGED,
    INVALID_APPOINTMENT_STATUS,
    NOT_DUE_TODAY,
    SLOT_NOT_ENDED,
    AppointmentConflict,
)
from app.services.status import APPOINTMENT_TRANSITIONS, CASE_TRANSITIONS, StatusChanger


class AttendanceService:
    """Registrar's marks on the day of the visit: arrival and no-show.

    Lock order (spec 11): slots -> appointments -> medical_cases. The appointment is read without a lock first only to
    learn the immutable `slot_id`.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        slots: SlotRepository,
        appointments: AppointmentRepository,
        cases: MedicalCaseRepository,
        status: StatusChanger,
        audit: AuditService,
        clock: Clock,
        calendar: LocalCalendar,
        settings: Settings,
    ) -> None:
        self.uow = uow
        self.slots = slots
        self.appointments = appointments
        self.cases = cases
        self.status = status
        self.audit = audit
        self.clock = clock
        self.calendar = calendar
        self.settings = settings

    async def mark_arrived(self, appointment_id: int, actor: User, ip: str | None = None) -> None:
        slot, appointment = await self._locked(appointment_id)
        if appointment.status is not AppointmentStatus.BOOKED:
            raise AppointmentConflict(INVALID_APPOINTMENT_STATUS)
        if self.calendar.day_of(self.clock.now()) != self.calendar.day_of(slot.start_at):
            raise AppointmentConflict(NOT_DUE_TODAY)
        try:
            await self._set_status(appointment, AppointmentStatus.ARRIVED, actor)
            await self._start_case(appointment, actor)
        except ConcurrentUpdate:  # the case was changed by someone else between our read and write
            await self.uow.rollback()
            raise AppointmentConflict(CASE_CHANGED) from None
        await self.audit.log(
            user_id=actor.id, action="appointment_arrive", entity_type="appointment", entity_id=appointment.id, ip=ip
        )
        await self.uow.commit()

    async def mark_no_show(self, appointment_id: int, actor: User, ip: str | None = None) -> None:
        slot, appointment = await self._locked(appointment_id)
        if appointment.status is not AppointmentStatus.BOOKED:
            raise AppointmentConflict(INVALID_APPOINTMENT_STATUS)
        if self.clock.now() < slot.end_at:
            raise AppointmentConflict(SLOT_NOT_ENDED)
        await self._set_status(appointment, AppointmentStatus.NO_SHOW, actor)  # the slot stays booked for good
        await self.audit.log(
            user_id=actor.id, action="appointment_no_show", entity_type="appointment", entity_id=appointment.id, ip=ip
        )
        await self.uow.commit()

    async def _locked(self, appointment_id: int) -> tuple[Slot, Appointment]:
        found = await self.appointments.find(appointment_id)
        if found is None:
            raise NotFound("Appointment not found")
        await self.uow.set_lock_timeout(self.settings.schedule_lock_timeout_ms)
        slot = await self.slots.get_locked(found.slot_id)
        appointment = await self.appointments.get_for_update(appointment_id)
        if slot is None or appointment is None:
            raise NotFound("Appointment not found")
        return slot, appointment

    async def _set_status(self, appointment: Appointment, to: AppointmentStatus, actor: User) -> None:
        appointment.updated_by = actor.id
        await self.status.change(
            appointment,
            entity_type="appointment",
            to_status=to,
            transitions=APPOINTMENT_TRANSITIONS,
            actor=actor.role,
            actor_id=actor.id,
        )

    async def _start_case(self, appointment: Appointment, actor: User) -> None:
        """First arrival: a registered case becomes in_progress; an unlinked or already running case is left alone."""
        if appointment.case_id is None:
            return
        case = await self.cases.get_for_update(appointment.case_id)
        if case is None or case.status is not CaseStatus.REGISTERED:
            return
        case.updated_by = actor.id
        await self.status.change(
            case,
            entity_type="case",
            to_status=CaseStatus.IN_PROGRESS,
            transitions=CASE_TRANSITIONS,
            actor=actor.role,
            actor_id=actor.id,
        )
