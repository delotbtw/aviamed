"""Server-side helpers for Jinja pages: auth cookies, safe `next` redirects, Origin (CSRF) check."""

from typing import Protocol
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from app.core.config import Settings, get_settings

DEFAULT_NEXT = "/cabinet"
AUTH_COOKIE_PATH = "/auth"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class SessionTokens(Protocol):
    access_token: str
    refresh_token: str


def safe_next(value: str | None) -> str:
    """Only a relative path starting with exactly one `/` is accepted."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return DEFAULT_NEXT
    if urlsplit(value).netloc or any(ord(c) < 32 for c in value):
        return DEFAULT_NEXT
    return value


def set_auth_cookies(response: Response, pair: SessionTokens, settings: Settings) -> None:
    secure = not settings.debug
    response.set_cookie(
        "access_token",
        pair.access_token,
        max_age=settings.access_token_ttl_min * 60,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        "refresh_token",
        pair.refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        path=AUTH_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def clear_auth_cookies(response: Response, settings: Settings | None = None) -> None:
    """Expire both cookies with the same attributes they were set with (a browser matches name+path)."""
    secure = not (settings or get_settings()).debug
    for name, path in (("access_token", "/"), ("refresh_token", AUTH_COOKIE_PATH)):
        response.delete_cookie(name, path=path, httponly=True, secure=secure, samesite="lax")


async def origin_check_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Cookie-authenticated unsafe requests must not carry a foreign Origin. Bearer API calls are exempt."""
    origin = request.headers.get("origin")
    if (
        origin
        and request.method in _UNSAFE_METHODS
        and "authorization" not in request.headers
        and ("access_token" in request.cookies or "refresh_token" in request.cookies)
        and urlsplit(origin).hostname != request.url.hostname
    ):
        return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
    return await call_next(request)
