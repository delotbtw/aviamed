"""Helpers shared by all page routers: rendering (full page or HTMX fragment) and reading form fields."""

from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import Path, Request, Response, status

from app.core.exceptions import AuthenticationFailed
from app.core.templating import templates
from app.models.user import User
from app.repositories.user import UserRepository
from app.schedule.queries import DoctorOption
from app.schedule.schemas import Id
from app.web.deps import ROLE_LABELS, is_htmx

ItemId = Annotated[Id, Path()]  # a database id in a URL, bounded like the API's
_NO_ECHO = frozenset({"password", "old_password", "new_password", "new_password_repeat"})


def _headers(response: Response, *, no_store: bool) -> Response:
    """Pages differ for plain and HTMX requests, and show data of one person: nothing is kept by caches."""
    response.headers["Vary"] = "HX-Request"
    if no_store:
        response.headers["Cache-Control"] = "no-store"
    if response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        response.headers["Retry-After"] = "1"  # a busy row lock: the user may press the button again
    return response


def fragment(request: Request, template: str, context: dict[str, Any], status_code: int = 200) -> Response:
    """A template that is only ever a piece of a page (HTMX answers)."""
    context = {"role_labels": ROLE_LABELS, **context}
    return _headers(templates.TemplateResponse(request, template, context, status_code=status_code), no_store=True)


def render(request: Request, page: str, partial: str, context: dict[str, Any], status_code: int = 200) -> Response:
    """Full page for a normal request, only the form fragment for HTMX."""
    context = {"role_labels": ROLE_LABELS, **context}
    template = partial if is_htmx(request) else page
    return _headers(templates.TemplateResponse(request, template, context, status_code=status_code), no_store=True)


def reject_filters(response: Response) -> Response:
    """Wrong filters: the typed values come back out of band, the table and the address stay as they were."""
    response.headers["HX-Reswap"] = "none"
    response.headers["HX-Push-Url"] = "false"
    return response


def doctor_choices(doctors: Iterable[DoctorOption]) -> list[tuple[int, str]]:
    """Options of a doctor select: (id, "ФИО, специальность")."""
    return [(d.id, f"{d.name}, {d.specialty}") for d in doctors]


async def form_payload(request: Request) -> dict[str, str]:
    """Form fields as a dict: values trimmed (passwords untouched), empty fields dropped."""
    form = await request.form()
    out: dict[str, str] = {}
    for key, value in form.items():
        if not isinstance(value, str):
            continue
        value = value if key in _NO_ECHO else value.strip()
        if value != "":
            out[key] = value
    return out


def echo(payload: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in payload.items() if k not in _NO_ECHO}


async def reload_actor(users: UserRepository, actor_id: int) -> User:
    """A service may roll the transaction back (lost race), which expires loaded objects: reload the actor by id."""
    actor = await users.get(actor_id)
    if actor is None:  # users are never deleted, so this is not expected
        raise AuthenticationFailed("Not authenticated")
    return actor
