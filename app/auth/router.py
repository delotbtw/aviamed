from fastapi import APIRouter, Request, Response, status

from app.auth.schemas import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenPair
from app.composition import AuthServiceDep
from app.core.deps import ClientIp, CurrentUser, UserAgent
from app.core.exceptions import InvalidInput

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
async def login(data: LoginRequest, auth: AuthServiceDep, user_agent: UserAgent, ip: ClientIp) -> TokenPair:
    return await auth.login(data.email, data.password, user_agent, ip)


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, auth: AuthServiceDep, user_agent: UserAgent, ip: ClientIp) -> TokenPair:
    return await auth.refresh(data.refresh_token, user_agent, ip)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, auth: AuthServiceDep, ip: ClientIp, data: RefreshRequest | None = None) -> Response:
    """Refresh token from the JSON body or, for browsers, from the `refresh_token` cookie."""
    token = data.refresh_token if data else request.cookies.get("refresh_token")
    if not token:
        raise InvalidInput("refresh_token is required")
    await auth.logout(token, ip)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(data: ChangePasswordRequest, user: CurrentUser, auth: AuthServiceDep, ip: ClientIp) -> None:
    await auth.change_password(user, data.old_password, data.new_password, ip)
