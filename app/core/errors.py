"""The single place where domain exceptions become HTTP responses."""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AuthenticationFailed,
    BadRequest,
    Conflict,
    DomainError,
    InvalidInput,
    NotFound,
    PermissionDenied,
    RateLimited,
)

_STATUS_BY_ERROR: tuple[tuple[type[DomainError], int], ...] = (
    (AuthenticationFailed, status.HTTP_401_UNAUTHORIZED),
    (PermissionDenied, status.HTTP_403_FORBIDDEN),
    (NotFound, status.HTTP_404_NOT_FOUND),
    (Conflict, status.HTTP_409_CONFLICT),
    (InvalidInput, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (BadRequest, status.HTTP_400_BAD_REQUEST),
    (RateLimited, status.HTTP_429_TOO_MANY_REQUESTS),
)


def http_status_for(exc: DomainError) -> int:
    for error_type, code in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            return code
    return status.HTTP_500_INTERNAL_SERVER_ERROR


async def _handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
    headers = None
    if isinstance(exc, RateLimited):
        headers = {"Retry-After": str(exc.retry_after)}
    elif isinstance(exc, AuthenticationFailed):
        headers = {"WWW-Authenticate": "Bearer"}
    return JSONResponse({"detail": str(exc)}, status_code=http_status_for(exc), headers=headers)


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Like FastAPI's default, but without echoing the offending input (it may be a password)."""
    errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
    return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(DomainError, _handle_domain_error)  # type: ignore[arg-type]


def not_implemented() -> HTTPException:
    """Placeholder for endpoints that are in the skeleton but have no logic yet."""
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Not implemented")
