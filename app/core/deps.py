from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.rbac import Action, Role, roles_for
from app.core.security import decode_token
from app.models.user import User
from app.repositories.user import UserRepository

SessionDep = Annotated[AsyncSession, Depends(get_session)]
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Access token from the Authorization header or the `access_token` cookie (Jinja pages)."""
    token = creds.credentials if creds else request.cookies.get("access_token")
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if not token:
        raise unauthorized
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise unauthorized from None
    if payload.get("type") != "access":
        raise unauthorized
    user = await UserRepository(session).get(int(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[..., User]:
    """Role gate run before the service. Data ownership is checked in services."""
    allowed = frozenset(roles)

    async def checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        return user

    return checker


def require_action(action: Action) -> Callable[..., User]:
    """Same as require_roles, but roles come from the matrix in rbac.PERMISSIONS."""
    return require_roles(*roles_for(action))
