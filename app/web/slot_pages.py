"""Page "Слоты приёма": admin and registrar manage the slots, a doctor reads his own."""

from datetime import datetime
from functools import partial
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.composition import ScheduleDirectoryDep, ScheduleQueriesDep, SlotServiceDep
from app.core.deps import CalendarDep, ClientIp, ClockDep, SettingsDep, UserRepoDep
from app.core.errors import http_status_for
from app.core.exceptions import DomainError, InvalidInput
from app.core.local_time import LocalCalendar
from app.core.rbac import Action, roles_for
from app.models.schedule import Slot
from app.models.user import User
from app.schedule.access import can_manage_slots, sees_all_doctors
from app.schedule.schemas import ManagedSlotsQuery, SlotCreate
from app.web import messages
from app.web import schedule_messages as texts
from app.web.dates import page_date
from app.web.deps import is_htmx, require_page_roles
from app.web.forms import ItemId, doctor_choices, echo, form_payload, reject_filters, reload_actor, render
from app.web.nav import PAGE_ACTIONS, SLOTS_PATH
from app.web.row_actions import RowResponder
from app.web.schedule_view import (
    QUEUE_LIMIT,
    Filters,
    board_filters_after_create,
    parse_slot_form,
    slot_request,
    slot_row,
    slots_filters,
)

router = APIRouter(include_in_schema=False)

_viewers = require_page_roles(*roles_for(PAGE_ACTIONS[SLOTS_PATH]))
_managers = require_page_roles(*roles_for(Action.SLOT_CREATE))


async def _board(
    user: User,
    queries: ScheduleQueriesDep,
    directory: ScheduleDirectoryDep,
    now: datetime,
    calendar: LocalCalendar,
    filters: Filters,
) -> dict[str, Any]:
    """Filter form and slot table. A doctor sees his own slots read-only, admin and registrar all or one doctor's."""
    can_manage, all_doctors = can_manage_slots(user), sees_all_doctors(user)
    day = filters.query.get("date_from", calendar.day_of(now))
    context: dict[str, Any] = {
        "user": user,
        "can_manage": can_manage,  # buttons and the slot form
        "all_doctors": all_doctors,  # the doctor column, the doctor filter and the doctor field of the form
        "filter_values": filters.values,
        "filter_errors": filters.errors,
        "oob": False,
        "doctors": doctor_choices(await directory.doctors()) if all_doctors else [],
        "rows": [],
        "day": page_date(day),
    }
    if not filters.errors:
        doctor_id = filters.query.get("doctor_id")
        query = ManagedSlotsQuery(doctor_id=doctor_id, date_from=day, date_to=day, limit=QUEUE_LIMIT)
        context["rows"] = [slot_row(i, now, manage=can_manage) for i in await queries.managed_slots(query, user)]
    return context


@router.get(SLOTS_PATH)
async def slots_page(
    request: Request,
    queries: ScheduleQueriesDep,
    directory: ScheduleDirectoryDep,
    clock: ClockDep,
    calendar: CalendarDep,
    user: Annotated[User, Depends(_viewers)],
):
    now = clock.now()
    filters = slots_filters(request.query_params, calendar.day_of(now), by_doctor=sees_all_doctors(user))
    context = {**await _board(user, queries, directory, now, calendar, filters), "values": {}, "errors": {}}
    if filters.errors:
        context["oob"] = is_htmx(request)
        return reject_filters(render(request, "cabinet/slots.html", "partials/slots_filter.html", context, 422))
    return render(request, "cabinet/slots.html", "partials/slots_table.html", context)


class SlotRows(RowResponder):
    template = "partials/slot_action.html"

    async def row(self, item_id: int, user: User):
        item = await self.queries.managed_slot(item_id, user)
        return slot_row(item, self.clock.now(), manage=can_manage_slots(user)) if item else None


SlotRowsDep = Annotated[SlotRows, Depends()]


@router.post(f"{SLOTS_PATH}/{{slot_id}}/close")
async def close_slot(
    request: Request,
    slot_id: ItemId,
    service: SlotServiceDep,
    responder: SlotRowsDep,
    ip: ClientIp,
    user: Annotated[User, Depends(_managers)],
):
    call = partial(service.close, slot_id, user, ip)
    return await responder.run(request, user, slot_id, call, texts.SLOT_ACTION)


@router.post(f"{SLOTS_PATH}/{{slot_id}}/reopen")
async def reopen_slot(
    request: Request,
    slot_id: ItemId,
    service: SlotServiceDep,
    responder: SlotRowsDep,
    ip: ClientIp,
    user: Annotated[User, Depends(_managers)],
):
    call = partial(service.reopen, slot_id, user, ip)
    return await responder.run(request, user, slot_id, call, texts.SLOT_ACTION)


# --------------------------------------------------------------------------- the form that adds slots


@router.post(f"{SLOTS_PATH}/new")
async def create_slots(
    request: Request,
    service: SlotServiceDep,
    queries: ScheduleQueriesDep,
    directory: ScheduleDirectoryDep,
    users: UserRepoDep,
    clock: ClockDep,
    calendar: CalendarDep,
    settings: SettingsDep,
    ip: ClientIp,
    user: Annotated[User, Depends(_managers)],
):
    payload = await form_payload(request)
    actor_id = user.id
    now = clock.now()
    form = parse_slot_form(payload, calendar, admin=True)
    errors, code = dict(form.errors), 422
    created: list[Slot] = []
    if not errors:
        data = slot_request(form)
        try:
            if isinstance(data, SlotCreate):
                created = [await service.create_slot(data, user, ip)]
            else:
                created = await service.create_batch(data, user, ip)
        except InvalidInput as exc:
            field, text = texts.slot_form_error(exc, settings, batch=form.slot_minutes is not None)
            errors[field] = text
        except DomainError as exc:
            code = http_status_for(exc)
            errors[messages.GENERAL] = texts.action_message(exc, texts.SLOT_CREATE)
    user = await reload_actor(users, actor_id)  # a rolled back transaction expires the loaded actor
    context: dict[str, Any] = {"values": echo(form.values), "errors": errors, "created": len(created)}
    if created:  # the day's table just changed: show the day the slots were made for
        filters = board_filters_after_create(form, admin=sees_all_doctors(user))
        context |= await _board(user, queries, directory, now, calendar, filters)
    elif not is_htmx(request):  # a whole page is needed anyway
        context |= await _board(
            user, queries, directory, now, calendar, slots_filters({}, calendar.day_of(now), by_doctor=False)
        )
    else:
        all_doctors = sees_all_doctors(user)
        doctors = doctor_choices(await directory.doctors()) if all_doctors else []
        context |= {"user": user, "all_doctors": all_doctors, "can_manage": can_manage_slots(user), "doctors": doctors}
    return render(request, "cabinet/slots.html", "partials/slot_form.html", context, 200 if created else code)
