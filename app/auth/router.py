from fastapi import APIRouter, HTTPException, Request, status

from app.auth.schemas import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenPair
from app.auth.service import AuthService, InvalidCredentials
from app.core.deps import CurrentUser, SessionDep

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
async def login(data: LoginRequest, request: Request, session: SessionDep) -> TokenPair:
    try:
        return await AuthService(session).login(data.email, data.password, request.headers.get("user-agent"))
    except InvalidCredentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from None


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, session: SessionDep) -> TokenPair:
    return await AuthService(session).refresh(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshRequest, session: SessionDep) -> None:
    await AuthService(session).logout(data.refresh_token)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(data: ChangePasswordRequest, user: CurrentUser, session: SessionDep) -> None:
    await AuthService(session).change_password(user.id, data.old_password, data.new_password)
