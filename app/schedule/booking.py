from app.audit.service import AuditService
from app.core.clock import Clock
from app.core.config import Settings
from app.core.exceptions import InvalidInput, NotFound
from app.core.rbac import Role
from app.core.uow import UnitOfWork
from app.models.enums import AppointmentStatus, SlotStatus
from app.models.schedule import Appointment, Slot
from app.models.user import User
from app.repositories.schedule import AppointmentRepository, SlotRepository
from app.repositories.user import UserRepository
from app.schedule.access import appointment_athlete_id
from app.schedule.exceptions import INVALID_APPOINTMENT_STATUS, SLOT_STARTED, AppointmentConflict, SlotTaken
from app.schedule.policy import BookingPolicy
from app.schedule.schemas import AppointmentCreate
from app.services.status import APPOINTMENT_TRANSITIONS, SLOT_TRANSITIONS, StatusChanger


class BookingService:
    """Booking and cancelling an appointment: appointment + slot + status_history + audit in one transaction.

    Lock order (spec 11): users (athlete) -> slots -> appointments -> medical_cases. Authorization that depends on
    immutable data (role, owner) runs before the locks, state checks run under them.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        slots: SlotRepository,
        appointments: AppointmentRepository,
        policy: BookingPolicy,
        status: StatusChanger,
        audit: AuditService,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self.uow = uow
        self.users = users
        self.slots = slots
        self.appointments = appointments
        self.policy = policy
        self.status = status
        self.audit = audit
        self.clock = clock
        self.settings = settings

    async def book(self, data: AppointmentCreate, actor: User, ip: str | None = None) -> Appointment:
        athlete_id = appointment_athlete_id(actor, data.athlete_id)
        await self.uow.set_lock_timeout(self.settings.schedule_lock_timeout_ms)

        athlete = await self.users.get_for_update(athlete_id)  # serializes bookings of one athlete
        if athlete is None or athlete.role is not Role.ATHLETE or not athlete.is_active:
            raise InvalidInput("athlete_id must point at an active athlete")
        slot = await self.slots.get_locked(data.slot_id)
        if slot is None:
            raise NotFound("Slot not found")
        await self.policy.check_slot(slot)
        if data.case_id is not None:
            await self.policy.check_case(data.case_id, athlete_id)
        await self.policy.check_athlete_capacity(athlete_id, slot)

        appointment = Appointment(
            slot_id=slot.id,
            athlete_id=athlete_id,
            case_id=data.case_id,
            status=AppointmentStatus.BOOKED,
            created_by=actor.id,
            updated_by=actor.id,
        )
        try:
            await self.appointments.add(appointment)
        except SlotTaken:  # the slot lock was bypassed: the partial unique index decides
            await self.uow.rollback()
            raise
        await self.status.created(
            entity_type="appointment", entity_id=appointment.id, status=AppointmentStatus.BOOKED, actor_id=actor.id
        )
        slot.updated_by = actor.id
        await self._move_slot(slot, SlotStatus.BOOKED, actor)
        await self.audit.log(
            user_id=actor.id, action="appointment_book", entity_type="appointment", entity_id=appointment.id, ip=ip
        )
        await self.uow.commit()
        return appointment

    async def cancel(self, appointment_id: int, actor: User, ip: str | None = None) -> None:
        # A foreign appointment of an athlete is excluded by the query itself, so it looks like a missing one.
        own = actor.id if actor.role is Role.ATHLETE else None
        found = await self.appointments.find(appointment_id, athlete_id=own)
        if found is None:
            raise NotFound("Appointment not found")
        await self.uow.set_lock_timeout(self.settings.schedule_lock_timeout_ms)

        slot = await self.slots.get_locked(found.slot_id)  # slot_id never changes: safe to take from the unlocked read
        appointment = await self.appointments.get_for_update(appointment_id)
        if slot is None or appointment is None:
            raise NotFound("Appointment not found")
        if appointment.status is AppointmentStatus.CANCELLED:
            await self.uow.rollback()  # idempotent: a double click or a lost race; release the locks, no second audit
            return
        if appointment.status is not AppointmentStatus.BOOKED:
            raise AppointmentConflict(INVALID_APPOINTMENT_STATUS)
        now = self.clock.now()
        deadline = slot.start_at if actor.role is Role.ATHLETE else slot.end_at
        if now >= deadline:
            raise AppointmentConflict(SLOT_STARTED)

        appointment.cancelled_at = now
        appointment.updated_by = actor.id
        await self.status.change(
            appointment,
            entity_type="appointment",
            to_status=AppointmentStatus.CANCELLED,
            transitions=APPOINTMENT_TRANSITIONS,
            actor=actor.role,
            actor_id=actor.id,
        )
        slot.updated_by = actor.id
        await self._move_slot(slot, SlotStatus.FREE, actor)
        await self.audit.log(
            user_id=actor.id, action="appointment_cancel", entity_type="appointment", entity_id=appointment.id, ip=ip
        )
        await self.uow.commit()

    async def _move_slot(self, slot: Slot, to: SlotStatus, actor: User) -> None:
        await self.status.change(
            slot,
            entity_type="slot",
            to_status=to,
            transitions=SLOT_TRANSITIONS,
            actor=actor.role,
            actor_id=actor.id,
        )
