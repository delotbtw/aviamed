"""Pages "Свободные слоты": the free-slot table with filters, the registrar's athlete search and booking."""

from collections.abc import Mapping
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response

from app.composition import BookingServiceDep, ScheduleDirectoryDep, ScheduleQueriesDep
from app.core.deps import ClientIp, UserRepoDep
from app.core.errors import http_status_for
from app.core.exceptions import DomainError
from app.core.rbac import Action, Role, roles_for
from app.models.user import User
from app.schedule.queries import ATHLETE_SEARCH_MIN_CHARS
from app.schedule.schemas import AppointmentCreate, FreeSlotsQuery
from app.web import schedule_messages as texts
from app.web.deps import is_htmx, require_page_roles
from app.web.forms import doctor_choices, form_payload, fragment, reject_filters, reload_actor, render
from app.web.nav import PAGE_ACTIONS, SCHEDULE_PATH
from app.web.schedule_view import PAGE_SIZE, Filters, free_slot_filters, parse_id, parse_offset

router = APIRouter(include_in_schema=False)

BOOK_ROLES = roles_for(Action.APPOINTMENT_BOOK)
PROXY_ROLES = BOOK_ROLES - {Role.ATHLETE}  # book for someone else, so they look an athlete up
_viewers = require_page_roles(*roles_for(PAGE_ACTIONS[SCHEDULE_PATH]))
_bookers = require_page_roles(*BOOK_ROLES)
_proxies = require_page_roles(*PROXY_ROLES)

LEADS = {
    Role.ATHLETE: "Выберите свободное время и нажмите «Записаться».",
    Role.REGISTRAR: "Найдите спортсмена, затем выберите слот и нажмите «Записаться».",
    Role.ADMIN: "Найдите спортсмена, затем выберите слот и нажмите «Записаться».",
    Role.DOCTOR: "Свободное время приёма всех врачей.",
}


async def _results(queries: ScheduleQueriesDep, filters: Filters, offset: int) -> dict[str, Any]:
    """One page of free slots; a 51st row only tells that "Показать ещё" is needed and is not shown."""
    query = FreeSlotsQuery(**filters.query, limit=PAGE_SIZE + 1, offset=offset)
    found = await queries.free_slots(query)
    more_url = None
    if len(found) > PAGE_SIZE:
        more_url = f"{SCHEDULE_PATH}?" + urlencode({**filters.values, "offset": offset + PAGE_SIZE})
    return {"slots": found[:PAGE_SIZE], "more_url": more_url, "offset": offset}


async def _options(directory: ScheduleDirectoryDep) -> dict[str, Any]:
    doctors = await directory.doctors()
    specialties = {d.specialty_id: d.specialty for d in doctors}
    return {
        "doctors": doctor_choices(doctors),
        "specialties": sorted(specialties.items(), key=lambda item: item[1]),
    }


@router.get(SCHEDULE_PATH)
async def schedule_page(
    request: Request,
    queries: ScheduleQueriesDep,
    directory: ScheduleDirectoryDep,
    user: Annotated[User, Depends(_viewers)],
):
    params: Mapping[str, str] = request.query_params
    filters = free_slot_filters(params)
    offset = parse_offset(params.get("offset"))
    context: dict[str, Any] = {
        "user": user,
        "staff": user.role in PROXY_ROLES,
        "bookable": user.role in BOOK_ROLES,
        "lead": LEADS[user.role],
        "values": filters.values,
        "errors": filters.errors,
        "oob": False,
        **await _options(directory),
    }
    if filters.errors:
        context |= {"slots": [], "more_url": None, "offset": 0, "oob": is_htmx(request)}
        return reject_filters(render(request, "cabinet/schedule.html", "partials/slot_filters.html", context, 422))
    context |= await _results(queries, filters, offset)
    partial = "partials/slot_rows.html" if offset else "partials/slot_results.html"
    return render(request, "cabinet/schedule.html", partial, context)


@router.get(f"{SCHEDULE_PATH}/athletes", dependencies=[Depends(_proxies)])
async def athlete_search(
    request: Request, directory: ScheduleDirectoryDep, q: Annotated[str, Query(max_length=100)] = ""
):
    context = {"athletes": await directory.find_athletes(q), "searched": len(q.strip()) >= ATHLETE_SEARCH_MIN_CHARS}
    return fragment(request, "partials/athlete_results.html", context)


@router.post(f"{SCHEDULE_PATH}/book")
async def book(
    request: Request,
    service: BookingServiceDep,
    queries: ScheduleQueriesDep,
    users: UserRepoDep,
    ip: ClientIp,
    user: Annotated[User, Depends(_bookers)],
):
    payload = await form_payload(request)
    slot_id = parse_id(payload.get("slot_id"))
    athlete_id = parse_id(payload.get("athlete_id"))
    if slot_id is None:
        return _booking_response(request, user, {"error": texts.CHOOSE_SLOT}, 422)
    if user.role in PROXY_ROLES and athlete_id is None:
        return _booking_response(request, user, {"error": texts.CHOOSE_ATHLETE}, 422)
    actor_id = user.id
    try:
        appointment = await service.book(AppointmentCreate(slot_id=slot_id, athlete_id=athlete_id), user, ip)
    except DomainError as exc:
        code = http_status_for(exc)
        user = await reload_actor(users, actor_id)  # a rolled back transaction expires the loaded actor
        context: dict[str, Any] = {"error": texts.action_message(exc, texts.BOOKING)}
        if code == 409:  # the list the user saw is out of date: send the current one
            filters = free_slot_filters(payload)
            context |= await _results(queries, Filters({}) if filters.errors else filters, 0) | {"bookable": True}
        return _booking_response(request, user, context, code)
    user = await reload_actor(users, actor_id)
    return _booking_response(request, user, {"booked": await queries.appointment(appointment.id, user)}, 200)


def _booking_response(request: Request, user: User, context: dict[str, Any], code: int) -> Response:
    return fragment(request, "partials/booking_result.html", {"user": user, **context}, code)
