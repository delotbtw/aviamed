from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_implemented
from app.models.user import User
from app.repositories.user import UserRepository
from app.users.schemas import AthleteRegister, ProfileUpdate, UserCreate


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def create_user(self, data: UserCreate) -> User:
        # TODO: hash password, create role-specific profile, audit.
        raise not_implemented()

    async def register_athlete(self, data: AthleteRegister, actor: User) -> User:
        # TODO: user + athlete_profile + consent in one transaction, audit.
        raise not_implemented()

    async def update_profile(self, user: User, data: ProfileUpdate) -> User:
        raise not_implemented()

    async def deactivate(self, user_id: int, actor: User) -> None:
        # Users are never deleted physically. TODO: also revoke refresh tokens.
        raise not_implemented()
