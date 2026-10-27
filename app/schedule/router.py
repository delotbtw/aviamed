from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import SessionDep, require_action
from app.core.rbac import Action
from app.schedule.schemas import AppointmentCreate, AppointmentRead, SlotCreate, SlotRead
from app.schedule.service import ScheduleService, SlotTaken

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("/slots", response_model=list[SlotRead], dependencies=[Depends(require_action(Action.SLOT_VIEW_FREE))])
async def free_slots(
    session: SessionDep, doctor_id: int | None = None, from_: datetime | None = None, to: datetime | None = None
):
    return await ScheduleService(session).free_slots(doctor_id, from_, to)


@router.post("/slots", response_model=SlotRead, status_code=status.HTTP_201_CREATED)
async def create_slot(data: SlotCreate, session: SessionDep, actor=Depends(require_action(Action.SLOT_CREATE))):
    return await ScheduleService(session).create_slot(data, actor)


@router.post("/appointments", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
async def book(data: AppointmentCreate, session: SessionDep, actor=Depends(require_action(Action.APPOINTMENT_BOOK))):
    try:
        return await ScheduleService(session).book(data, actor)
    except SlotTaken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slot is already taken") from None


@router.post("/appointments/{appointment_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel(
    appointment_id: int, session: SessionDep, actor=Depends(require_action(Action.APPOINTMENT_CANCEL))
) -> None:
    await ScheduleService(session).cancel(appointment_id, actor)


@router.post("/appointments/{appointment_id}/arrive", status_code=status.HTTP_204_NO_CONTENT)
async def arrive(appointment_id: int, session: SessionDep, actor=Depends(require_action(Action.ARRIVAL_MARK))) -> None:
    await ScheduleService(session).mark_arrived(appointment_id, actor)
