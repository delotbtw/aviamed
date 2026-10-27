"""Domain exceptions. Services raise these and know nothing about HTTP; the mapping lives in core/errors.py."""


class DomainError(Exception):
    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.default_message)

    default_message = "Error"


class AuthenticationFailed(DomainError):
    default_message = "Not authenticated"


class PermissionDenied(DomainError):
    default_message = "Forbidden"


class NotFound(DomainError):
    default_message = "Not found"


class Conflict(DomainError):
    default_message = "Conflict"


class InvalidInput(DomainError):
    default_message = "Invalid input"


class BadRequest(DomainError):
    default_message = "Bad request"


class InvalidCredentials(AuthenticationFailed):
    """Deliberately generic: do not reveal whether the user exists."""

    default_message = "Invalid email or password"


class InvalidRefreshToken(AuthenticationFailed):
    default_message = "Invalid refresh token"


class InvalidOldPassword(BadRequest):
    default_message = "Invalid old password"


class RateLimited(DomainError):
    default_message = "Too many attempts, try again later"

    def __init__(self, retry_after: int) -> None:
        super().__init__()
        self.retry_after = retry_after
