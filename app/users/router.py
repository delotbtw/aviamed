from fastapi import APIRouter, Depends, status

from app.core.deps import CurrentUser, SessionDep, require_action
from app.core.rbac import Action
from app.users.schemas import AthleteRegister, ProfileUpdate, UserCreate, UserRead
from app.users.service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead)
async def update_me(data: ProfileUpdate, user: CurrentUser, session: SessionDep) -> UserRead:
    return UserRead.model_validate(await UserService(session).update_profile(user, data))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate, session: SessionDep, actor=Depends(require_action(Action.USER_CREATE))
) -> UserRead:
    return UserRead.model_validate(await UserService(session).create_user(data))


@router.post("/athletes", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_athlete(
    data: AthleteRegister, session: SessionDep, actor=Depends(require_action(Action.ATHLETE_REGISTER))
) -> UserRead:
    return UserRead.model_validate(await UserService(session).register_athlete(data, actor))


@router.post("/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate(user_id: int, session: SessionDep, actor=Depends(require_action(Action.USER_CREATE))) -> None:
    await UserService(session).deactivate(user_id, actor)
