from sqlalchemy import select

from app.models.user import AthleteProfile, DoctorProfile, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email))


class AthleteProfileRepository(BaseRepository[AthleteProfile]):
    model = AthleteProfile

    async def list_by_coach(self, coach_id: int) -> list[AthleteProfile]:
        result = await self.session.scalars(select(AthleteProfile).where(AthleteProfile.coach_id == coach_id))
        return list(result)


class DoctorProfileRepository(BaseRepository[DoctorProfile]):
    model = DoctorProfile
