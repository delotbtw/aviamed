"""Building blocks shared by the user services: account creation and reference checks."""

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import Conflict, InvalidInput
from app.core.rbac import Role
from app.core.security import PasswordHasher
from app.core.uow import UnitOfWork
from app.models.user import User
from app.repositories.base import violated_constraint
from app.repositories.reference import SpecialtyRepository, SportRepository
from app.repositories.user import UserRepository

USERS_EMAIL_CONSTRAINT = "uq_users_email"


class AccountCreator:
    """Creates the `users` row: unique email, hashed password. The caller owns the transaction."""

    def __init__(self, users: UserRepository, hasher: PasswordHasher, uow: UnitOfWork) -> None:
        self.users = users
        self.uow = uow
        self.hasher = hasher

    async def create(
        self,
        *,
        email: str,
        password: str,
        role: Role,
        last_name: str,
        first_name: str,
        middle_name: str | None,
        phone: str | None,
    ) -> User:
        if await self.users.get_by_email(email) is not None:
            raise Conflict("Email is already registered")
        user = User(
            email=email,
            password_hash=await self.hasher.hash(password),
            role=role,
            last_name=last_name,
            first_name=first_name,
            middle_name=middle_name,
            phone=phone,
            is_active=True,
        )
        try:
            return await self.users.add(user)
        except IntegrityError as e:  # lost a race against a concurrent registration
            if violated_constraint(e) != USERS_EMAIL_CONSTRAINT:
                raise
            await self.uow.rollback()  # the session is unusable after a failed flush; callers may render a response
            raise Conflict("Email is already registered") from None


class ReferenceValidator:
    """Checks that ids from the request point at existing reference data."""

    def __init__(self, sports: SportRepository, specialties: SpecialtyRepository, users: UserRepository) -> None:
        self.sports = sports
        self.specialties = specialties
        self.users = users

    async def sport(self, sport_id: int | None) -> None:
        if sport_id is not None and await self.sports.get(sport_id) is None:
            raise InvalidInput("Unknown sport_id")

    async def specialty(self, specialty_id: int) -> None:
        if await self.specialties.get(specialty_id) is None:
            raise InvalidInput("Unknown specialty_id")

    async def coach(self, coach_id: int | None) -> None:
        if coach_id is None:
            return
        coach = await self.users.get(coach_id)
        if coach is None or coach.role is not Role.COACH or not coach.is_active:
            raise InvalidInput("coach_id must point at an active coach")
