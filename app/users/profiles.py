"""Role-specific profile creation (strategy per role). Adding a role means adding a creator, not editing a service."""

from typing import Protocol

from app.models.user import CoachProfile, DoctorProfile, StaffProfile, User
from app.repositories.user import CoachProfileRepository, DoctorProfileRepository, StaffProfileRepository
from app.users.accounts import ReferenceValidator
from app.users.schemas import UserCreate


class ProfileCreator(Protocol):
    async def validate(self, data: UserCreate) -> None:
        """Checks that run before the account is created (e.g. referenced ids exist)."""

    async def create(self, user: User, data: UserCreate) -> None: ...


class DoctorProfileCreator:
    def __init__(self, doctors: DoctorProfileRepository, references: ReferenceValidator) -> None:
        self.doctors = doctors
        self.references = references

    async def validate(self, data: UserCreate) -> None:
        await self.references.specialty(data.specialty_id)  # presence is guaranteed by the schema

    async def create(self, user: User, data: UserCreate) -> None:
        await self.doctors.add(
            DoctorProfile(
                user_id=user.id,
                specialty_id=data.specialty_id,
                cabinet=data.cabinet,
                can_issue_conclusion=data.can_issue_conclusion,
            )
        )


class CoachProfileCreator:
    def __init__(self, coaches: CoachProfileRepository, references: ReferenceValidator) -> None:
        self.coaches = coaches
        self.references = references

    async def validate(self, data: UserCreate) -> None:
        await self.references.sport(data.sport_id)

    async def create(self, user: User, data: UserCreate) -> None:
        await self.coaches.add(CoachProfile(user_id=user.id, sport_id=data.sport_id))


class StaffProfileCreator:
    """Registrar and admin."""

    def __init__(self, staff: StaffProfileRepository) -> None:
        self.staff = staff

    async def validate(self, data: UserCreate) -> None:
        return None

    async def create(self, user: User, data: UserCreate) -> None:
        await self.staff.add(StaffProfile(user_id=user.id, position=data.position, workplace=data.workplace))
