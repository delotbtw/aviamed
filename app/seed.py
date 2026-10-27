"""Demo data for local development and demos. Never run automatically and never part of migrations."""

from dataclasses import dataclass
from datetime import date

from app.core.rbac import Role
from app.models.enums import Sex
from app.models.reference import Specialty, Sport
from app.models.system import Consent
from app.models.user import AthleteProfile, CoachProfile, DoctorProfile, StaffProfile, User
from app.repositories.reference import SpecialtyRepository, SportRepository
from app.repositories.system import ConsentRepository
from app.repositories.user import (
    AthleteProfileRepository,
    CoachProfileRepository,
    DoctorProfileRepository,
    StaffProfileRepository,
    UserRepository,
)
from app.users.accounts import AccountCreator

DEMO_PASSWORD = "Demo12345!"  # demo only, publicly known

SPORTS = (
    "Плавание",
    "Лёгкая атлетика",
    "Бокс",
    "Борьба",
    "Футбол",
    "Баскетбол",
    "Волейбол",
    "Лыжные гонки",
    "Гимнастика",
    "Хоккей",
)
# Specialists of the in-depth examination (docs/06 section 4).
SPECIALTIES = (
    "Спортивная медицина",
    "Терапия",
    "Травматология и ортопедия",
    "Хирургия",
    "Неврология",
    "Оториноларингология",
    "Офтальмология",
    "Кардиология",
    "Акушерство и гинекология",
    "Урология-андрология",
    "Дерматовенерология",
    "Стоматология",
)
SPORT_MEDICINE = "Спортивная медицина"
DEMO_SPORT = "Плавание"
DEMO_CONSENT_NUMBER = "DEMO-0001"

DEMO_EMAILS = {
    Role.ADMIN: "demo-admin@example.com",
    Role.REGISTRAR: "demo-registrar@example.com",
    Role.DOCTOR: "demo-doctor@example.com",
    Role.COACH: "demo-coach@example.com",
    Role.ATHLETE: "demo-athlete@example.com",
}


@dataclass(frozen=True)
class DemoLogin:
    role: Role
    email: str
    password: str
    created: bool


class DemoSeeder:
    """Idempotent: everything is looked up by name/email first and created only if missing. Caller commits."""

    def __init__(
        self,
        accounts: AccountCreator,
        users: UserRepository,
        sports: SportRepository,
        specialties: SpecialtyRepository,
        doctors: DoctorProfileRepository,
        coaches: CoachProfileRepository,
        staff: StaffProfileRepository,
        athletes: AthleteProfileRepository,
        consents: ConsentRepository,
        password: str = DEMO_PASSWORD,
    ) -> None:
        self.accounts = accounts
        self.users = users
        self.sports = sports
        self.specialties = specialties
        self.doctors = doctors
        self.coaches = coaches
        self.staff = staff
        self.athletes = athletes
        self.consents = consents
        self.password = password

    async def seed(self) -> list[DemoLogin]:
        sport_ids = {name: (await self._sport(name)).id for name in SPORTS}
        specialty_ids = {name: (await self._specialty(name)).id for name in SPECIALTIES}

        logins = [
            await self._staff(Role.ADMIN, "Админов", "Андрей"),
            await self._staff(Role.REGISTRAR, "Регистраторова", "Раиса"),
            await self._person(Role.DOCTOR, "Врачебный", "Виктор", specialty_id=specialty_ids[SPORT_MEDICINE]),
            await self._person(Role.COACH, "Тренерова", "Татьяна", sport_id=sport_ids[DEMO_SPORT]),
        ]
        coach = await self.users.get_by_email(DEMO_EMAILS[Role.COACH])
        logins.append(
            await self._person(Role.ATHLETE, "Спортсменов", "Сергей", sport_id=sport_ids[DEMO_SPORT], coach=coach)
        )
        return logins

    async def _sport(self, name: str) -> Sport:
        return await self.sports.get_by_name(name) or await self.sports.add(Sport(name=name))

    async def _specialty(self, name: str) -> Specialty:
        return await self.specialties.get_by_name(name) or await self.specialties.add(Specialty(name=name))

    async def _staff(self, role: Role, last_name: str, first_name: str) -> DemoLogin:
        return await self._get_or_create(
            role, last_name, first_name, lambda user: self.staff.add(StaffProfile(user_id=user.id, position="Демо"))
        )

    async def _person(
        self,
        role: Role,
        last_name: str,
        first_name: str,
        *,
        specialty_id: int | None = None,
        sport_id: int | None = None,
        coach: User | None = None,
    ) -> DemoLogin:
        async def profile(user: User) -> None:
            match role:
                case Role.DOCTOR:
                    await self.doctors.add(
                        DoctorProfile(
                            user_id=user.id, specialty_id=specialty_id, cabinet="101", can_issue_conclusion=True
                        )
                    )
                case Role.COACH:
                    await self.coaches.add(CoachProfile(user_id=user.id, sport_id=sport_id))
                case Role.ATHLETE:
                    await self.athletes.add(
                        AthleteProfile(
                            user_id=user.id,
                            birth_date=date(2004, 3, 12),
                            sex=Sex.MALE,
                            sport_id=sport_id,
                            coach_id=coach.id if coach else None,
                        )
                    )
                    await self.consents.add(
                        Consent(
                            user_id=user.id,
                            consent_type="personal_data_health",
                            paper_number=DEMO_CONSENT_NUMBER,
                            signed_at=date.today(),
                        )
                    )

        return await self._get_or_create(role, last_name, first_name, profile)

    async def _get_or_create(self, role: Role, last_name: str, first_name: str, add_profile) -> DemoLogin:
        email = DEMO_EMAILS[role]
        if await self.users.get_by_email(email) is not None:
            return DemoLogin(role, email, self.password, created=False)
        user = await self.accounts.create(
            email=email,
            password=self.password,
            role=role,
            last_name=last_name,
            first_name=first_name,
            middle_name=None,
            phone=None,
        )
        await add_profile(user)
        return DemoLogin(role, email, self.password, created=True)
