"""Jinja2/HTMX pages. Thin: parse the form, call an existing service through DI, render the result."""

from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, FastAPI, Form, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.auth.schemas import ChangePasswordRequest, LoginRequest
from app.composition import AthleteRegistrationDep, AuthServiceDep, UserServiceDep
from app.core.deps import ClientIp, SettingsDep, UserAgent, UserRepoDep
from app.core.errors import http_status_for
from app.core.exceptions import AuthenticationFailed, DomainError, RateLimited
from app.core.rbac import Action, Role, roles_for
from app.core.templating import templates
from app.core.web import clear_auth_cookies, safe_next, set_auth_cookies
from app.models.enums import TrainingStage
from app.models.user import User
from app.repositories.user import UserRepository
from app.users.schemas import AthleteRegister, UserCreate
from app.web import messages
from app.web.dates import normalize_dates, show_dates
from app.web.deps import (
    ROLE_LABELS,
    OptionalPageUser,
    PageResponse,
    PageUser,
    SpecialtyRepoDep,
    SportRepoDep,
    is_htmx,
    require_page_roles,
)
from app.web.nav import nav_links

router = APIRouter(include_in_schema=False)

WEB_LOGOUT_PATH = "/auth/web-logout"  # inside the refresh cookie's Path=/auth, so the browser sends the cookie here
_NO_ECHO = frozenset({"password", "old_password", "new_password", "new_password_repeat"})
STAFF_ROLES = (Role.DOCTOR, Role.REGISTRAR, Role.COACH, Role.ADMIN)


def register_web_handlers(app: FastAPI) -> None:
    templates.env.globals["nav_links"] = nav_links

    async def _page_response(request: Request, exc: PageResponse) -> Response:
        return exc.response

    app.add_exception_handler(PageResponse, _page_response)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- helpers


def render(request: Request, page: str, partial: str, context: dict[str, Any], status_code: int = 200) -> Response:
    """Full page for a normal request, only the form fragment for HTMX."""
    return templates.TemplateResponse(
        request, partial if is_htmx(request) else page, {"role_labels": ROLE_LABELS, **context}, status_code=status_code
    )


def redirect(request: Request, url: str, *, clear_cookies: bool = False) -> Response:
    """303 for plain requests, HX-Redirect for HTMX (so the whole page is replaced)."""
    if is_htmx(request):
        response: Response = Response(status_code=status.HTTP_200_OK, headers={"HX-Redirect": url})
    else:
        response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    if clear_cookies:
        clear_auth_cookies(response)
    return response


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


# --------------------------------------------------------------------------- landing, login / logout / session


@router.get("/")
async def index(request: Request, user: OptionalPageUser):
    return templates.TemplateResponse(request, "index.html", {"user": user, "role_labels": ROLE_LABELS})


def _login_context(next_: str | None, **extra: Any) -> dict[str, Any]:
    return {"next": next_ or "", "email": "", "error": None, "notice": None, "user": None, **extra}


@router.get("/login")
async def login_page(request: Request, user: OptionalPageUser, next: str | None = None, changed: bool = False):
    if user is not None:
        return RedirectResponse(safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
    notice = "Пароль изменён, войдите заново" if changed else None
    return templates.TemplateResponse(request, "login.html", _login_context(next, notice=notice))


@router.post("/login")
async def login_submit(
    request: Request,
    auth: AuthServiceDep,
    settings: SettingsDep,
    user_agent: UserAgent,
    ip: ClientIp,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next_form: Annotated[str | None, Form(alias="next")] = None,
    next_query: Annotated[str | None, Query(alias="next")] = None,
):
    next_ = next_form or next_query
    error, code, headers = None, status.HTTP_401_UNAUTHORIZED, {}
    try:
        data = LoginRequest(email=email, password=password)
        pair = await auth.login(data.email, data.password, user_agent, ip)
    except ValidationError:
        error = "Неверный email или пароль"
    except RateLimited as exc:
        error, code, headers = (
            messages.rate_limit_message(exc),
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"Retry-After": str(exc.retry_after)},
        )
    except AuthenticationFailed:
        error = "Неверный email или пароль"
    else:
        response = redirect(request, safe_next(next_))
        set_auth_cookies(response, pair, settings)
        return response
    context = _login_context(next_, email=email.strip(), error=error)
    template = "partials/login_form.html" if is_htmx(request) else "login.html"
    return templates.TemplateResponse(request, template, context, status_code=code, headers=headers)


async def _end_session(auth: AuthServiceDep, token: str | None, ip: str | None) -> Response:
    if token:
        await auth.logout(token, ip)  # idempotent: unknown/revoked tokens are ignored
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_auth_cookies(response)
    return response


@router.post("/logout")
async def logout(request: Request, auth: AuthServiceDep, ip: ClientIp):
    """The refresh cookie has Path=/auth, so a browser does not send it here.

    Without it, the POST is forwarded (307, method and body kept) to WEB_LOGOUT_PATH, where the cookie is available.
    The cookie's path is not widened: it stays out of reach of every other page.
    """
    token = request.cookies.get("refresh_token")
    if token or not (request.cookies.get("access_token")):
        return await _end_session(auth, token, ip)
    return RedirectResponse(WEB_LOGOUT_PATH, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post(WEB_LOGOUT_PATH)
async def web_logout(request: Request, auth: AuthServiceDep, ip: ClientIp):
    return await _end_session(auth, request.cookies.get("refresh_token"), ip)


@router.get("/auth/session")
async def auth_session(
    request: Request,
    auth: AuthServiceDep,
    settings: SettingsDep,
    user_agent: UserAgent,
    ip: ClientIp,
    next: str | None = None,
):
    target = safe_next(next)
    login_url = "/login?" + urlencode({"next": target}, safe="/")
    token = request.cookies.get("refresh_token")
    if not token:
        return RedirectResponse(login_url, status_code=status.HTTP_303_SEE_OTHER)
    try:
        pair = await auth.refresh(token, user_agent, ip)
    except DomainError:
        response = RedirectResponse(login_url, status_code=status.HTTP_303_SEE_OTHER)
        clear_auth_cookies(response)
        return response
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(response, pair, settings)
    return response


# --------------------------------------------------------------------------- cabinet


@router.get("/cabinet")
async def cabinet(request: Request, user: PageUser):
    return templates.TemplateResponse(
        request,
        "cabinet/index.html",
        {
            "user": user,
            "role_labels": ROLE_LABELS,
        },
    )


@router.get("/cabinet/password")
async def password_page(request: Request, user: PageUser):
    return render(request, "cabinet/password.html", "partials/password_form.html", {"user": user, "errors": {}})


@router.post("/cabinet/password")
async def password_submit(request: Request, user: PageUser, auth: AuthServiceDep, ip: ClientIp):
    payload = await form_payload(request)
    errors: dict[str, str] = {}
    code = status.HTTP_422_UNPROCESSABLE_CONTENT
    if payload.get("new_password", "") != payload.get("new_password_repeat", ""):
        errors["new_password_repeat"] = "Пароли не совпадают"
    else:
        try:
            data = ChangePasswordRequest(
                old_password=payload.get("old_password", ""), new_password=payload.get("new_password", "")
            )
            await auth.change_password(user, data.old_password, data.new_password, ip)
        except ValidationError as exc:
            errors = {
                ("new_password" if k == messages.GENERAL else k): v for k, v in messages.validation_errors(exc).items()
            }
        except DomainError as exc:
            code = http_status_for(exc)
            errors[messages.GENERAL] = (
                messages.rate_limit_message(exc) if isinstance(exc, RateLimited) else messages.domain_message(exc)
            )
        else:
            return redirect(request, "/login?changed=1", clear_cookies=True)
    return render(
        request, "cabinet/password.html", "partials/password_form.html", {"user": user, "errors": errors}, code
    )


# --------------------------------------------------------------------------- forms: athlete, staff user


async def _reload(users: UserRepository, actor_id: int) -> User:
    """A service may roll the transaction back (lost race), which expires loaded objects: reload the actor by id."""
    actor = await users.get(actor_id)
    if actor is None:  # users are never deleted, so this is not expected
        raise AuthenticationFailed("Not authenticated")
    return actor


async def _athlete_context(user: User, sports: SportRepoDep, users: UserRepoDep, **extra: Any) -> dict[str, Any]:
    return {
        "user": user,
        "sports": [(o.id, o.name) for o in await sports.list_all()],
        "coaches": [(c.id, f"{c.last_name} {c.first_name}") for c in await users.list_active_coaches()],
        "stages": list(TrainingStage),
        "values": {},
        "errors": {},
        "success": False,
        **extra,
    }


_athlete_roles = require_page_roles(*roles_for(Action.ATHLETE_REGISTER))
_user_roles = require_page_roles(*roles_for(Action.USER_CREATE))


@router.get("/cabinet/athletes/new")
async def athlete_form(
    request: Request, sports: SportRepoDep, users: UserRepoDep, user: User = Depends(_athlete_roles)
):
    return render(
        request, "cabinet/athlete_new.html", "partials/athlete_form.html", await _athlete_context(user, sports, users)
    )


@router.post("/cabinet/athletes/new")
async def athlete_submit(
    request: Request,
    service: AthleteRegistrationDep,
    sports: SportRepoDep,
    users: UserRepoDep,
    ip: ClientIp,
    user: User = Depends(_athlete_roles),
):
    typed = await form_payload(request)
    payload, date_errors = normalize_dates(typed)
    errors: dict[str, str] = {}
    code = status.HTTP_422_UNPROCESSABLE_CONTENT
    actor_id = user.id
    try:
        data = AthleteRegister.model_validate(payload)
        if not date_errors:  # a date that could not be read is reported together with the other field errors
            await service.register(data, user, ip)
    except ValidationError as exc:
        errors = messages.validation_errors(exc)
    except DomainError as exc:
        code = http_status_for(exc)
        errors[messages.GENERAL] = messages.domain_message(exc)
        user = await _reload(users, actor_id)
    else:
        if not date_errors:
            context = await _athlete_context(user, sports, users, success=True)
            return render(request, "cabinet/athlete_new.html", "partials/athlete_form.html", context)
    context = await _athlete_context(
        user, sports, users, values=show_dates(echo(typed)), errors={**errors, **date_errors}
    )
    return render(request, "cabinet/athlete_new.html", "partials/athlete_form.html", context, code)


async def _user_context(
    user: User, sports: SportRepoDep, specialties: SpecialtyRepoDep, **extra: Any
) -> dict[str, Any]:
    context = {
        "user": user,
        "sports": [(o.id, o.name) for o in await sports.list_all()],
        "specialties": [(o.id, o.name) for o in await specialties.list_all()],
        "role_options": [(r.value, ROLE_LABELS[r]) for r in STAFF_ROLES],
        "values": {},
        "errors": {},
        "success": False,
        **extra,
    }
    # Only a known staff role reaches the template (it goes into an Alpine expression and picks the visible fieldset).
    chosen = context["values"].get("role")
    context["selected_role"] = chosen if chosen in {r.value for r in STAFF_ROLES} else Role.DOCTOR.value
    return context


@router.get("/cabinet/users/new")
async def user_form(
    request: Request, sports: SportRepoDep, specialties: SpecialtyRepoDep, user: User = Depends(_user_roles)
):
    context = await _user_context(user, sports, specialties)
    return render(request, "cabinet/user_new.html", "partials/user_form.html", context)


@router.post("/cabinet/users/new")
async def user_submit(
    request: Request,
    service: UserServiceDep,
    sports: SportRepoDep,
    specialties: SpecialtyRepoDep,
    users: UserRepoDep,
    ip: ClientIp,
    user: User = Depends(_user_roles),
):
    payload = await form_payload(request)
    errors: dict[str, str] = {}
    code = status.HTTP_422_UNPROCESSABLE_CONTENT
    actor_id = user.id
    try:
        await service.create_user(UserCreate.model_validate(payload), user, ip)
    except ValidationError as exc:
        errors = messages.validation_errors(exc)
    except DomainError as exc:
        code = http_status_for(exc)
        errors[messages.GENERAL] = messages.domain_message(exc)
        user = await _reload(users, actor_id)
    else:
        context = await _user_context(user, sports, specialties, success=True)
        return render(request, "cabinet/user_new.html", "partials/user_form.html", context)
    context = await _user_context(user, sports, specialties, values=echo(payload), errors=errors)
    return render(request, "cabinet/user_new.html", "partials/user_form.html", context, code)
