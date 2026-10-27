from datetime import datetime

from sqlalchemy import select

from app.models.enums import SlotStatus
from app.models.schedule import Appointment, Slot
from app.repositories.base import BaseRepository


class SlotRepository(BaseRepository[Slot]):
    model = Slot

    async def list_free(
        self, *, doctor_id: int | None = None, from_: datetime | None = None, to: datetime | None = None
    ) -> list[Slot]:
        stmt = select(Slot).where(Slot.status == SlotStatus.FREE).order_by(Slot.start_at)
        if doctor_id is not None:
            stmt = stmt.where(Slot.doctor_id == doctor_id)
        if from_ is not None:
            stmt = stmt.where(Slot.start_at >= from_)
        if to is not None:
            stmt = stmt.where(Slot.start_at < to)
        return list(await self.session.scalars(stmt))


class AppointmentRepository(BaseRepository[Appointment]):
    model = Appointment

    async def list_by_athlete(self, athlete_id: int) -> list[Appointment]:
        result = await self.session.scalars(select(Appointment).where(Appointment.athlete_id == athlete_id))
        return list(result)
