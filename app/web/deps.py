"""Page-level dependencies: cookie authentication with redirects, role gates, HTML responses."""

from collections.abc import Callable
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.deps import AccessTokensDep, SessionDep, UserRepoDep, get_current_user
from app.core.exceptions import AuthenticationFailed
from app.core.rbac import Role
from app.core.templating import templates
from app.models.user import User
from app.repositories.reference import SpecialtyRepository, SportRepository

ROLE_LABELS = {
    Role.ADMIN: "Администратор",
    Role.REGISTRAR: "Регистратура",
    Role.DOCTOR: "Врач",
    Role.COACH: "Тренер",
    Role.ATHLETE: "Спортсмен",
}


class PageResponse(Exception):
    """Raised by page dependencies to short-circuit the request with a ready response."""

    def __init__(self, response: Response) -> None:
        self.response = response


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def session_url(request: Request) -> str:
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return "/auth/session?" + urlencode({"next": target}, safe="/")


def forbidden_response(request: Request, user: User) -> Response:
    if is_htmx(request):  # a whole page must never land inside a form: send the browser to the cabinet instead
        return Response(status_code=status.HTTP_403_FORBIDDEN, headers={"HX-Redirect": "/cabinet"})
    return templates.TemplateResponse(
        request, "errors/forbidden.html", {"user": user, "role_labels": ROLE_LABELS}, status_code=403
    )


async def get_optional_page_user(request: Request, users: UserRepoDep, access_tokens: AccessTokensDep) -> User | None:
    try:
        return await get_current_user(request, users, access_tokens, None)
    except AuthenticationFailed:
        return None


OptionalPageUser = Annotated[User | None, Depends(get_optional_page_user)]


async def get_page_user(request: Request, user: OptionalPageUser) -> User:
    """Authenticated page user; otherwise redirect through /auth/session (HX-Redirect for HTMX)."""
    if user is not None:
        return user
    if is_htmx(request):
        raise PageResponse(
            Response(status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": session_url(request)})
        )
    raise PageResponse(RedirectResponse(session_url(request), status_code=status.HTTP_303_SEE_OTHER))


PageUser = Annotated[User, Depends(get_page_user)]


def require_page_roles(*roles: Role) -> Callable[..., User]:
    allowed = frozenset(roles)

    async def checker(request: Request, user: PageUser) -> User:
        if user.role not in allowed:
            raise PageResponse(forbidden_response(request, user))
        return user

    return checker


def get_sport_repo(session: SessionDep) -> SportRepository:
    return SportRepository(session)


def get_specialty_repo(session: SessionDep) -> SpecialtyRepository:
    return SpecialtyRepository(session)


SportRepoDep = Annotated[SportRepository, Depends(get_sport_repo)]
SpecialtyRepoDep = Annotated[SpecialtyRepository, Depends(get_specialty_repo)]
