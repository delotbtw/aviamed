from sqlalchemy import select

from app.core.rbac import Role
from app.models.user import AthleteProfile, CoachProfile, DoctorProfile, StaffProfile, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email))

    async def list_active_coaches(self) -> list[User]:
        stmt = (
            select(User)
            .where(User.role == Role.COACH, User.is_active.is_(True))
            .order_by(User.last_name, User.first_name, User.id)
        )
        return list(await self.session.scalars(stmt))


class AthleteProfileRepository(BaseRepository[AthleteProfile]):
    model = AthleteProfile

    async def list_by_coach(self, coach_id: int) -> list[AthleteProfile]:
        result = await self.session.scalars(select(AthleteProfile).where(AthleteProfile.coach_id == coach_id))
        return list(result)


class DoctorProfileRepository(BaseRepository[DoctorProfile]):
    model = DoctorProfile


class CoachProfileRepository(BaseRepository[CoachProfile]):
    model = CoachProfile


class StaffProfileRepository(BaseRepository[StaffProfile]):
    model = StaffProfile
