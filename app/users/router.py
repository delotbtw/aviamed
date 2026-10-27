from fastapi import APIRouter, Depends, status

from app.composition import AccountLifecycleDep, AthleteRegistrationDep, UserServiceDep
from app.core.deps import ClientIp, CurrentUser, require_action
from app.core.rbac import Action
from app.models.user import User
from app.users.schemas import AthleteRegister, ProfileUpdate, UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserRead)
async def update_me(data: ProfileUpdate, user: CurrentUser, service: UserServiceDep, ip: ClientIp) -> User:
    return await service.update_profile(user, data, ip)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate, service: UserServiceDep, ip: ClientIp, actor: User = Depends(require_action(Action.USER_CREATE))
) -> User:
    return await service.create_user(data, actor, ip)


@router.post("/athletes", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_athlete(
    data: AthleteRegister,
    service: AthleteRegistrationDep,
    ip: ClientIp,
    actor: User = Depends(require_action(Action.ATHLETE_REGISTER)),
) -> User:
    return await service.register(data, actor, ip)


@router.post("/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate(
    user_id: int,
    service: AccountLifecycleDep,
    ip: ClientIp,
    actor: User = Depends(require_action(Action.USER_DEACTIVATE)),
) -> None:
    await service.deactivate(user_id, actor, ip)
