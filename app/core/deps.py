"""Infrastructure dependencies shared by all features: session, settings, Redis, current user, role gates.

Feature services are wired in `app/composition.py` (the composition root); nothing here imports a feature.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_tokens import AccessTokenService, build_access_tokens
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.exceptions import AuthenticationFailed, PermissionDenied
from app.core.rbac import Action, Role, roles_for
from app.core.redis import get_redis
from app.core.uow import SqlAlchemyUnitOfWork, UnitOfWork
from app.models.user import User
from app.repositories.user import UserRepository

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
_bearer = HTTPBearer(auto_error=False)


def get_redis_client() -> Redis:
    """Looked up per request: `app.core.redis.get_redis()` stays the single place tests swap the client."""
    return get_redis()


RedisDep = Annotated[Redis, Depends(get_redis_client)]


def get_unit_of_work(session: SessionDep) -> UnitOfWork:
    return SqlAlchemyUnitOfWork(session)


UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_unit_of_work)]


def get_client_ip(request: Request) -> str | None:
    """Peer address of the connection. In production uvicorn (`--proxy-headers`, FORWARDED_ALLOW_IPS limited to the
    nginx address) replaces it with the value nginx sets from `$remote_addr`; XFF is never read here directly."""
    return request.client.host if request.client else None


ClientIp = Annotated[str | None, Depends(get_client_ip)]
UserAgent = Annotated[str | None, Header(include_in_schema=False)]


def get_user_repo(session: SessionDep) -> UserRepository:
    return UserRepository(session)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repo)]


def get_access_tokens(settings: SettingsDep) -> AccessTokenService:
    return build_access_tokens(settings)


AccessTokensDep = Annotated[AccessTokenService, Depends(get_access_tokens)]


async def get_current_user(
    request: Request,
    users: UserRepoDep,
    access_tokens: AccessTokensDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Access token from the Authorization header or the `access_token` cookie (Jinja pages)."""
    token = creds.credentials if creds else request.cookies.get("access_token")
    if not token:
        raise AuthenticationFailed("Not authenticated")
    user = await users.get(access_tokens.parse(token).user_id)
    if user is None or not user.is_active:
        raise AuthenticationFailed("Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[..., User]:
    """Role gate run before the service. Data ownership is checked in services."""
    allowed = frozenset(roles)

    async def checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDenied("Forbidden")
        return user

    return checker


def require_action(action: Action) -> Callable[..., User]:
    """Same as require_roles, but roles come from the matrix in rbac.PERMISSIONS."""
    return require_roles(*roles_for(action))
