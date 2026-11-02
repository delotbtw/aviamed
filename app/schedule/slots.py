from datetime import UTC, datetime

from app.audit.service import AuditService
from app.core.clock import Clock
from app.core.config import Settings
from app.core.exceptions import InvalidInput, NotFound
from app.core.rbac import Role
from app.core.uow import UnitOfWork
from app.models.enums import SlotStatus
from app.models.schedule import Slot
from app.models.user import User
from app.repositories.schedule import SlotRepository
from app.repositories.user import UserRepository
from app.schedule.access import require_slot_manager, slot_owner_id
from app.schedule.exceptions import SLOT_BOOKED, SLOT_STARTED, SLOTS_OVERLAP, SlotOverlap, SlotUnavailable
from app.schedule.planning import Interval, SlotPlanner
from app.schedule.schemas import SlotBatchCreate, SlotCreate
from app.services.status import SLOT_TRANSITIONS, StatusChanger


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class SlotService:
    """Admin's and registrar's slot management: create, batch, close, reopen.

    Locks (spec 11): creation takes the doctor's `users` row; close/reopen take the `slots` row.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        slots: SlotRepository,
        status: StatusChanger,
        audit: AuditService,
        planner: SlotPlanner,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self.uow = uow
        self.users = users
        self.slots = slots
        self.status = status
        self.audit = audit
        self.planner = planner
        self.clock = clock
        self.settings = settings

    async def create_slot(self, data: SlotCreate, actor: User, ip: str | None = None) -> Slot:
        doctor_id = slot_owner_id(actor, data.doctor_id)
        interval = self.planner.single(data.start_at, data.end_at)
        [slot] = await self._create(doctor_id, [interval], actor, ip)
        return slot

    async def create_batch(self, data: SlotBatchCreate, actor: User, ip: str | None = None) -> list[Slot]:
        doctor_id = slot_owner_id(actor, data.doctor_id)
        intervals = self.planner.batch(data.start_at, data.end_at, data.slot_minutes)
        return await self._create(doctor_id, intervals, actor, ip)

    async def close(self, slot_id: int, actor: User, ip: str | None = None) -> None:
        slot = await self._slot_locked(slot_id, actor)
        if slot.status is SlotStatus.CLOSED:
            await self.uow.rollback()  # idempotent: release the lock, no second audit record
            return
        if slot.status is SlotStatus.BOOKED:
            raise SlotUnavailable(SLOT_BOOKED)
        await self._move(slot, SlotStatus.CLOSED, "slot_close", actor, ip)

    async def reopen(self, slot_id: int, actor: User, ip: str | None = None) -> None:
        slot = await self._slot_locked(slot_id, actor)
        if slot.status is SlotStatus.FREE:
            await self.uow.rollback()
            return
        if slot.status is SlotStatus.BOOKED:
            raise SlotUnavailable(SLOT_BOOKED)
        if slot.start_at <= self.clock.now():
            raise SlotUnavailable(SLOT_STARTED)
        await self._move(slot, SlotStatus.FREE, "slot_reopen", actor, ip)

    # ------------------------------------------------------------------ internals

    async def _create(self, doctor_id: int, intervals: list[Interval], actor: User, ip: str | None) -> list[Slot]:
        await self.uow.set_lock_timeout(self.settings.schedule_lock_timeout_ms)
        doctor = await self.users.get_for_update(doctor_id)  # serializes slot creation of one doctor
        if doctor is None or doctor.role is not Role.DOCTOR or not doctor.is_active:
            raise InvalidInput("doctor_id must point at an active doctor")

        await self._reject_overlaps(doctor_id, intervals)
        slots = [
            Slot(doctor_id=doctor_id, start_at=start, end_at=end, status=SlotStatus.FREE, created_by=actor.id)
            for start, end in intervals
        ]
        try:
            await self.slots.add_many(slots)
        except SlotOverlap:  # the lock was bypassed or a bug: the exclusion constraint is the last word
            await self.uow.rollback()
            raise
        for slot in slots:
            await self.audit.log(user_id=actor.id, action="slot_create", entity_type="slot", entity_id=slot.id, ip=ip)
        await self.uow.commit()
        return slots

    async def _reject_overlaps(self, doctor_id: int, intervals: list[Interval]) -> None:
        existing = await self.slots.overlapping(doctor_id, intervals[0][0], intervals[-1][1])
        for start, end in intervals:  # intervals are ordered: the first hit is the first offending slot
            if any(s.start_at < end and s.end_at > start for s in existing):
                raise SlotOverlap(SLOTS_OVERLAP if len(intervals) == 1 else f"{SLOTS_OVERLAP}: {_iso(start)}")

    async def _slot_locked(self, slot_id: int, actor: User) -> Slot:
        """Admin and registrar reach any slot; the role is checked before anything is read."""
        require_slot_manager(actor)
        await self.uow.set_lock_timeout(self.settings.schedule_lock_timeout_ms)
        slot = await self.slots.get_locked(slot_id)
        if slot is None:
            raise NotFound("Slot not found")
        return slot

    async def _move(self, slot: Slot, to: SlotStatus, action: str, actor: User, ip: str | None) -> None:
        slot.updated_by = actor.id
        await self.status.change(
            slot,
            entity_type="slot",
            to_status=to,
            transitions=SLOT_TRANSITIONS,
            actor=actor.role,
            actor_id=actor.id,
        )
        await self.audit.log(user_id=actor.id, action=action, entity_type="slot", entity_id=slot.id, ip=ip)
        await self.uow.commit()
