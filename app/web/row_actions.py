"""Buttons on a table row (cancel, arrive, close, ...): run the action, answer with the row as it is now."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Request, Response

from app.composition import ScheduleQueriesDep
from app.core.deps import CalendarDep, ClockDep, UserRepoDep
from app.core.errors import http_status_for
from app.core.exceptions import DomainError
from app.core.rbac import Role
from app.models.user import User
from app.schedule.access import can_manage_slots, sees_all_doctors
from app.web import schedule_messages as texts
from app.web.forms import fragment, reload_actor


class RowResponder:
    """Runs `call`; whatever happens, the answer is the current row (when it is still visible) and the reason of a
    failure under it. Subclasses say how to read the row and which template draws it."""

    template: str

    def __init__(self, users: UserRepoDep, queries: ScheduleQueriesDep, clock: ClockDep, calendar: CalendarDep) -> None:
        self.users = users
        self.queries = queries
        self.clock = clock
        self.calendar = calendar

    async def row(self, item_id: int, user: User) -> Any | None:
        raise NotImplementedError

    async def run(
        self,
        request: Request,
        user: User,
        item_id: int,
        call: Callable[[], Awaitable[None]],
        messages: Mapping[str, str],
    ) -> Response:
        actor_id = user.id
        error, code = None, 200
        try:
            await call()
        except DomainError as exc:
            error, code = texts.action_message(exc, messages), http_status_for(exc)
        user = await reload_actor(self.users, actor_id)  # a rolled back transaction expires the loaded actor
        context = {
            "user": user,
            "row": await self.row(item_id, user),
            "staff": user.role is not Role.ATHLETE,
            "can_manage": can_manage_slots(user),
            "all_doctors": sees_all_doctors(user),
            "error": error,
        }
        return fragment(request, self.template, context, code)
