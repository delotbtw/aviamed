from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.composition import (
    AttendanceServiceDep,
    BookingServiceDep,
    ScheduleQueriesDep,
    SlotServiceDep,
)
from app.core.deps import ClientIp, require_action
from app.core.rbac import Action
from app.models.schedule import Appointment, Slot
from app.models.user import User
from app.schedule.schemas import (
    AppointmentCreate,
    AppointmentListItem,
    AppointmentRead,
    AppointmentsQuery,
    FreeSlotsQuery,
    ManagedSlotsQuery,
    SlotBatchCreate,
    SlotCreate,
    SlotListItem,
    SlotManageItem,
    SlotRead,
)

router = APIRouter(prefix="/schedule", tags=["schedule"])

PathId = Annotated[int, Path(ge=1, le=2**31 - 1)]
SlotManager = Annotated[User, Depends(require_action(Action.SLOT_CREATE))]
SlotViewer = Annotated[User, Depends(require_action(Action.SLOT_VIEW))]


@router.get("/slots", response_model=list[SlotListItem], dependencies=[Depends(require_action(Action.SLOT_VIEW_FREE))])
async def free_slots(query: Annotated[FreeSlotsQuery, Query()], queries: ScheduleQueriesDep):
    return await queries.free_slots(query)


@router.get("/slots/all", response_model=list[SlotManageItem])
async def managed_slots(query: Annotated[ManagedSlotsQuery, Query()], queries: ScheduleQueriesDep, actor: SlotViewer):
    return await queries.managed_slots(query, actor)


@router.post("/slots", response_model=SlotRead, status_code=status.HTTP_201_CREATED)
async def create_slot(data: SlotCreate, service: SlotServiceDep, ip: ClientIp, actor: SlotManager) -> Slot:
    return await service.create_slot(data, actor, ip)


@router.post("/slots/batch", response_model=list[SlotRead], status_code=status.HTTP_201_CREATED)
async def create_batch(data: SlotBatchCreate, service: SlotServiceDep, ip: ClientIp, actor: SlotManager) -> list[Slot]:
    return await service.create_batch(data, actor, ip)


@router.post("/slots/{slot_id}/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_slot(slot_id: PathId, service: SlotServiceDep, ip: ClientIp, actor: SlotManager) -> None:
    await service.close(slot_id, actor, ip)


@router.post("/slots/{slot_id}/reopen", status_code=status.HTTP_204_NO_CONTENT)
async def reopen_slot(slot_id: PathId, service: SlotServiceDep, ip: ClientIp, actor: SlotManager) -> None:
    await service.reopen(slot_id, actor, ip)


@router.post("/appointments", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
async def book(
    data: AppointmentCreate,
    service: BookingServiceDep,
    ip: ClientIp,
    actor: User = Depends(require_action(Action.APPOINTMENT_BOOK)),
) -> Appointment:
    return await service.book(data, actor, ip)


@router.get("/appointments", response_model=list[AppointmentListItem])
async def appointments(
    query: Annotated[AppointmentsQuery, Query()],
    queries: ScheduleQueriesDep,
    actor: User = Depends(require_action(Action.APPOINTMENT_VIEW)),
):
    return await queries.appointments(query, actor)


@router.post("/appointments/{appointment_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel(
    appointment_id: PathId,
    service: BookingServiceDep,
    ip: ClientIp,
    actor: User = Depends(require_action(Action.APPOINTMENT_CANCEL)),
) -> None:
    await service.cancel(appointment_id, actor, ip)


@router.post("/appointments/{appointment_id}/arrive", status_code=status.HTTP_204_NO_CONTENT)
async def arrive(
    appointment_id: PathId,
    service: AttendanceServiceDep,
    ip: ClientIp,
    actor: User = Depends(require_action(Action.ARRIVAL_MARK)),
) -> None:
    await service.mark_arrived(appointment_id, actor, ip)


@router.post("/appointments/{appointment_id}/no-show", status_code=status.HTTP_204_NO_CONTENT)
async def no_show(
    appointment_id: PathId,
    service: AttendanceServiceDep,
    ip: ClientIp,
    actor: User = Depends(require_action(Action.ARRIVAL_MARK)),
) -> None:
    await service.mark_no_show(appointment_id, actor, ip)
