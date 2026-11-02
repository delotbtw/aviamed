"""Pages "Моя запись" (athlete) and "Очередь записей" (registrar, admin), and the actions on their rows."""

from collections.abc import Mapping
from datetime import timedelta
from functools import partial
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.composition import AttendanceServiceDep, BookingServiceDep, ScheduleDirectoryDep, ScheduleQueriesDep
from app.core.deps import CalendarDep, ClientIp, ClockDep
from app.core.rbac import Action, Role, roles_for
from app.models.user import User
from app.schedule.schemas import AppointmentsQuery
from app.web import schedule_messages as texts
from app.web.deps import is_htmx, require_page_roles
from app.web.forms import ItemId, doctor_choices, reject_filters, render
from app.web.nav import APPOINTMENTS_PATH, PAGE_ACTIONS
from app.web.row_actions import RowResponder
from app.web.schedule_view import (
    HISTORY_DAYS,
    QUEUE_LIMIT,
    STATUS_OPTIONS,
    appointment_row,
    queue_filters,
    split_appointments,
)

router = APIRouter(include_in_schema=False)

_viewers = require_page_roles(*roles_for(PAGE_ACTIONS[APPOINTMENTS_PATH]))
_cancellers = require_page_roles(*roles_for(Action.APPOINTMENT_CANCEL))
_registrars = require_page_roles(*roles_for(Action.ARRIVAL_MARK))


@router.get(APPOINTMENTS_PATH)
async def appointments_page(
    request: Request,
    queries: ScheduleQueriesDep,
    directory: ScheduleDirectoryDep,
    clock: ClockDep,
    calendar: CalendarDep,
    user: Annotated[User, Depends(_viewers)],
):
    now = clock.now()
    context: dict[str, Any] = {"user": user, "staff": user.role is not Role.ATHLETE}
    if user.role is Role.ATHLETE:
        since = calendar.day_of(now) - timedelta(days=HISTORY_DAYS)
        items = await queries.appointments(AppointmentsQuery(date_from=since, limit=QUEUE_LIMIT), user)
        upcoming, history = split_appointments(items, now)
        context |= {
            "upcoming": [appointment_row(i, user.role, now, calendar) for i in upcoming],
            "history": [appointment_row(i, user.role, now, calendar) for i in history],
        }
        return render(request, "cabinet/appointments.html", "cabinet/appointments.html", context)

    params: Mapping[str, str] = request.query_params
    filters = queue_filters(params, calendar.day_of(now))
    athlete_id = filters.query.get("athlete_id")
    context |= {
        "values": filters.values,
        "errors": filters.errors,
        "oob": False,
        "doctors": doctor_choices(await directory.doctors()),
        "statuses": STATUS_OPTIONS,
        "athlete_name": await directory.athlete(athlete_id, user) if athlete_id else "",
        "rows": [],
        "limit": QUEUE_LIMIT,
        "truncated": False,
    }
    if filters.errors:
        context["oob"] = is_htmx(request)
        return reject_filters(render(request, "cabinet/appointments.html", "partials/queue_filters.html", context, 422))
    items = await queries.appointments(AppointmentsQuery(**filters.query, limit=QUEUE_LIMIT), user)
    context["rows"] = [appointment_row(i, user.role, now, calendar) for i in items]
    context["truncated"] = len(items) == QUEUE_LIMIT
    return render(request, "cabinet/appointments.html", "partials/queue_results.html", context)


class AppointmentRows(RowResponder):
    template = "partials/appointment_action.html"

    async def row(self, item_id: int, user: User):
        item = await self.queries.appointment(item_id, user)
        return appointment_row(item, user.role, self.clock.now(), self.calendar) if item else None


ResponderDep = Annotated[AppointmentRows, Depends()]


@router.post(f"{APPOINTMENTS_PATH}/{{appointment_id}}/cancel")
async def cancel(
    request: Request,
    appointment_id: ItemId,
    service: BookingServiceDep,
    responder: ResponderDep,
    ip: ClientIp,
    user: Annotated[User, Depends(_cancellers)],
):
    call = partial(service.cancel, appointment_id, user, ip)
    return await responder.run(request, user, appointment_id, call, texts.CANCEL)


@router.post(f"{APPOINTMENTS_PATH}/{{appointment_id}}/arrive")
async def arrive(
    request: Request,
    appointment_id: ItemId,
    service: AttendanceServiceDep,
    responder: ResponderDep,
    ip: ClientIp,
    user: Annotated[User, Depends(_registrars)],
):
    call = partial(service.mark_arrived, appointment_id, user, ip)
    return await responder.run(request, user, appointment_id, call, texts.ARRIVE)


@router.post(f"{APPOINTMENTS_PATH}/{{appointment_id}}/no-show")
async def no_show(
    request: Request,
    appointment_id: ItemId,
    service: AttendanceServiceDep,
    responder: ResponderDep,
    ip: ClientIp,
    user: Annotated[User, Depends(_registrars)],
):
    call = partial(service.mark_no_show, appointment_id, user, ip)
    return await responder.run(request, user, appointment_id, call, texts.NO_SHOW)
