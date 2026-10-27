from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_implemented
from app.models.schedule import Appointment, Slot
from app.models.user import User
from app.repositories.schedule import AppointmentRepository, SlotRepository
from app.schedule.schemas import AppointmentCreate, SlotCreate


class SlotTaken(Exception):
    """Slot already booked (unique violation on appointments.slot_id)."""


class ScheduleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.slots = SlotRepository(session)
        self.appointments = AppointmentRepository(session)

    async def free_slots(self, doctor_id: int | None, from_: datetime | None, to: datetime | None) -> list[Slot]:
        # TODO: Redis cache of free slots.
        return await self.slots.list_free(doctor_id=doctor_id, from_=from_, to=to)

    async def create_slot(self, data: SlotCreate, actor: User) -> Slot:
        # TODO: doctors create only own slots; validate start < end.
        raise not_implemented()

    async def book(self, data: AppointmentCreate, actor: User) -> Appointment:
        # TODO: ownership by role; insert appointment, slot -> booked, catch IntegrityError -> SlotTaken.
        raise not_implemented()

    async def cancel(self, appointment_id: int, actor: User) -> None:
        # TODO: change_status(APPOINTMENT_TRANSITIONS), free the slot.
        raise not_implemented()

    async def mark_arrived(self, appointment_id: int, actor: User) -> None:
        # TODO: booked -> arrived; first arrival moves the case registered -> in_progress.
        raise not_implemented()
