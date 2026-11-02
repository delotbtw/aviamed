"""Demo data for local development and demos. Never run automatically and never part of migrations.

Idempotent: everything is looked up by name/email first and created only if missing. Blocks (reference data, users,
slots, appointments) are committed separately by `DemoSeeder`.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from app.core.clock import Clock
from app.core.local_time import LocalCalendar
from app.core.rbac import Role
from app.core.security import PasswordHasher
from app.core.uow import UnitOfWork
from app.models.enums import Sex, TrainingStage
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
from app.seed_schedule import DemoActors, DemoAppointments, DemoSlots
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
CONSENT_TYPE = "personal_data_health"

DEMO_DOMAIN = "example.com"  # the seed refuses a database with users outside this domain

DEMO_EMAILS = {
    Role.ADMIN: "demo-admin@example.com",
    Role.REGISTRAR: "demo-registrar@example.com",
    Role.DOCTOR: "demo-doctor@example.com",
    Role.COACH: "demo-coach@example.com",
    Role.ATHLETE: "demo-athlete@example.com",
}

# (last name, first name, middle name)
type Name = tuple[str, str, str]

ADMIN_NAMES: tuple[Name, ...] = (("Громов", "Андрей", "Викторович"),)
REGISTRAR_NAMES: tuple[Name, ...] = (
    ("Регистратова", "Раиса", "Николаевна"),
    ("Кузнецова", "Ольга", "Павловна"),
)
# (name, specialty); the first one is the only sports doctor who issues conclusions.
DOCTORS: tuple[tuple[Name, str], ...] = (
    (("Врачебный", "Виктор", "Сергеевич"), SPORT_MEDICINE),
    (("Лебедева", "Марина", "Игоревна"), "Терапия"),
    (("Орлов", "Дмитрий", "Алексеевич"), "Травматология и ортопедия"),
    (("Соколова", "Елена", "Борисовна"), "Неврология"),
    (("Белов", "Константин", "Юрьевич"), "Кардиология"),
    (("Фомина", "Наталья", "Андреевна"), "Офтальмология"),
)
COACHES: tuple[tuple[Name, str], ...] = (
    (("Тренерова", "Татьяна", "Михайловна"), "Плавание"),
    (("Макаров", "Олег", "Петрович"), "Бокс"),
    (("Зайцева", "Ирина", "Владимировна"), "Волейбол"),
)
ATHLETE_COUNT = 40
# 20 male and 20 female athletes: names are combined by coprime strides, so no full name repeats.
MALE_LAST = (
    "Иванов", "Смирнов", "Попов", "Волков", "Новиков", "Морозов", "Петров", "Козлов", "Степанов", "Николаев",
    "Орлов", "Андреев", "Макаров", "Никитин", "Захаров", "Зайцев", "Соловьёв", "Борисов", "Яковлев", "Григорьев",
)  # fmt: skip
FEMALE_LAST = tuple(f"{n}а" for n in MALE_LAST)
MALE_FIRST = (
    "Александр", "Дмитрий", "Максим", "Артём", "Михаил", "Иван", "Даниил", "Кирилл", "Егор", "Никита",
    "Илья", "Андрей", "Тимофей", "Роман", "Матвей", "Владислав", "Павел", "Денис", "Глеб", "Сергей",
)  # fmt: skip
FEMALE_FIRST = (
    "Анна", "Мария", "Алиса", "Дарья", "Полина", "Екатерина", "Виктория", "Ксения", "Софья", "Анастасия",
    "Варвара", "Алина", "Елизавета", "Милана", "Вероника", "Юлия", "Кристина", "Диана", "Арина", "Валерия",
)  # fmt: skip
MALE_MIDDLE = (
    "Александрович", "Дмитриевич", "Сергеевич", "Андреевич", "Михайлович", "Иванович", "Алексеевич", "Владимирович",
    "Николаевич", "Павлович", "Игоревич", "Олегович", "Викторович", "Артёмович", "Романович", "Евгеньевич",
    "Денисович", "Максимович", "Кириллович", "Юрьевич",
)  # fmt: skip
FEMALE_MIDDLE = tuple(f"{n[:-2]}на" if n.endswith("ич") else n for n in MALE_MIDDLE)
FACULTIES = ("Институт №1", "Институт №3", "Институт №4", "Институт №6", "Институт №8")


def demo_email(role: Role, number: int) -> str:
    """The first account of a role is `demo-<role>@...`, the others `demo-<role>-N@...` with N from 2."""
    return DEMO_EMAILS[role] if number == 1 else f"demo-{role.value}-{number}@example.com"


def athlete_name(index: int) -> tuple[Name, Sex]:
    j = index // 2
    if index % 2 == 0:
        return (MALE_LAST[j], MALE_FIRST[(j * 7) % 20], MALE_MIDDLE[(j * 3) % 20]), Sex.MALE
    return (FEMALE_LAST[j], FEMALE_FIRST[(j * 7 + 3) % 20], FEMALE_MIDDLE[(j * 3 + 1) % 20]), Sex.FEMALE


@dataclass(frozen=True)
class DemoLogin:
    role: Role
    email: str
    password: str
    created: bool


@dataclass
class DemoPeople:
    logins: list[DemoLogin] = field(default_factory=list)
    admin_id: int = 0
    registrar_id: int = 0
    doctor_ids: list[int] = field(default_factory=list)
    athlete_ids: list[int] = field(default_factory=list)

    def actors(self) -> DemoActors:
        return DemoActors(self.admin_id, self.registrar_id, self.doctor_ids, self.athlete_ids)


@dataclass
class DemoResult:
    logins: list[DemoLogin]
    slots_created: int
    appointments_created: Counter[str]


class CachedHasher:
    """Hashes each password once: all demo accounts share the (publicly known) password, Argon2 is slow."""

    def __init__(self, inner: PasswordHasher) -> None:
        self.inner = inner
        self._hashes: dict[str, str] = {}

    async def hash(self, password: str) -> str:
        if password not in self._hashes:
            self._hashes[password] = await self.inner.hash(password)
        return self._hashes[password]

    async def verify(self, password: str, password_hash: str) -> bool:
        return await self.inner.verify(password, password_hash)

    async def verify_dummy(self, password: str) -> None:
        await self.inner.verify_dummy(password)


class DemoReference:
    """Sports and specialties; returns name -> id maps."""

    def __init__(self, sports: SportRepository, specialties: SpecialtyRepository) -> None:
        self.sports = sports
        self.specialties = specialties

    async def ensure(self) -> tuple[dict[str, int], dict[str, int]]:
        sport_ids = {name: (await self._sport(name)).id for name in SPORTS}
        specialty_ids = {name: (await self._specialty(name)).id for name in SPECIALTIES}
        return sport_ids, specialty_ids

    async def _sport(self, name: str) -> Sport:
        return await self.sports.get_by_name(name) or await self.sports.add(Sport(name=name))

    async def _specialty(self, name: str) -> Specialty:
        return await self.specialties.get_by_name(name) or await self.specialties.add(Specialty(name=name))


class DemoUsers:
    """Accounts and profiles of all roles. An existing email is left untouched ("exists")."""

    def __init__(
        self,
        accounts: AccountCreator,
        users: UserRepository,
        doctors: DoctorProfileRepository,
        coaches: CoachProfileRepository,
        staff: StaffProfileRepository,
        athletes: AthleteProfileRepository,
        consents: ConsentRepository,
        clock: Clock,
        calendar: LocalCalendar,
        password: str = DEMO_PASSWORD,
    ) -> None:
        self.accounts = accounts
        self.users = users
        self.doctors = doctors
        self.coaches = coaches
        self.staff = staff
        self.athletes = athletes
        self.consents = consents
        self.clock = clock
        self.calendar = calendar
        self.password = password

    async def ensure(self, sport_ids: dict[str, int], specialty_ids: dict[str, int]) -> DemoPeople:
        people = DemoPeople()
        admin = await self._staff(people, Role.ADMIN, 1, ADMIN_NAMES[0])
        registrars = [await self._staff(people, Role.REGISTRAR, n, name) for n, name in enumerate(REGISTRAR_NAMES, 1)]
        people.admin_id, people.registrar_id = admin.id, registrars[0].id
        for n, (name, specialty) in enumerate(DOCTORS, 1):
            doctor = await self._doctor(people, n, name, specialty_ids[specialty])
            people.doctor_ids.append(doctor.id)
        coach_users = [
            (await self._coach(people, n, name, sport_ids[sport]), sport_ids[sport])
            for n, (name, sport) in enumerate(COACHES, 1)
        ]
        for index in range(ATHLETE_COUNT):
            coach, sport_id = coach_users[index % len(coach_users)]
            athlete = await self._athlete(people, index, coach.id, sport_id)
            people.athlete_ids.append(athlete.id)
        return people

    async def _staff(self, people: DemoPeople, role: Role, number: int, name: Name) -> User:
        async def profile(user: User) -> None:
            await self.staff.add(StaffProfile(user_id=user.id, position="Демо"))

        return await self._get_or_create(people, role, number, name, profile)

    async def _doctor(self, people: DemoPeople, number: int, name: Name, specialty_id: int) -> User:
        async def profile(user: User) -> None:
            await self.doctors.add(
                DoctorProfile(
                    user_id=user.id,
                    specialty_id=specialty_id,
                    cabinet=str(100 + number),
                    can_issue_conclusion=number == 1,  # the only sports doctor
                )
            )

        return await self._get_or_create(people, Role.DOCTOR, number, name, profile)

    async def _coach(self, people: DemoPeople, number: int, name: Name, sport_id: int) -> User:
        async def profile(user: User) -> None:
            await self.coaches.add(CoachProfile(user_id=user.id, sport_id=sport_id))

        return await self._get_or_create(people, Role.COACH, number, name, profile)

    async def _athlete(self, people: DemoPeople, index: int, coach_id: int, sport_id: int) -> User:
        name, sex = athlete_name(index)

        async def profile(user: User) -> None:
            await self.athletes.add(
                AthleteProfile(
                    user_id=user.id,
                    birth_date=date(2002 + index % 5, 1 + index % 12, 1 + (index * 7) % 28),
                    sex=sex,
                    faculty=FACULTIES[index % len(FACULTIES)],
                    study_group=f"М{1 + index % 8}О-{101 + index % 4}Б-{22 + index % 3}",
                    sport_id=sport_id,
                    training_stage=TrainingStage.TRAINING if index % 3 else TrainingStage.MASS,
                    coach_id=coach_id,
                )
            )
            await self.consents.add(
                Consent(
                    user_id=user.id,
                    consent_type=CONSENT_TYPE,
                    paper_number=f"DEMO-{index + 1:04d}",
                    signed_at=self.calendar.day_of(self.clock.now()),
                )
            )

        return await self._get_or_create(people, Role.ATHLETE, index + 1, name, profile)

    async def _get_or_create(self, people: DemoPeople, role: Role, number: int, name: Name, add_profile) -> User:
        email = demo_email(role, number)
        user = await self.users.get_by_email(email)
        if user is not None:
            people.logins.append(DemoLogin(role, email, self.password, created=False))
            return user
        last_name, first_name, middle_name = name
        user = await self.accounts.create(
            email=email,
            password=self.password,
            role=role,
            last_name=last_name,
            first_name=first_name,
            middle_name=middle_name,
            phone=None,
        )
        await add_profile(user)
        people.logins.append(DemoLogin(role, email, self.password, created=True))
        return user


class DemoSeeder:
    """Runs the blocks in order, each in its own transaction. Safe to repeat."""

    def __init__(
        self,
        uow: UnitOfWork,
        reference: DemoReference,
        users: DemoUsers,
        slots: DemoSlots,
        appointments: DemoAppointments,
    ) -> None:
        self.uow = uow
        self.reference = reference
        self.users = users
        self.slots = slots
        self.appointments = appointments

    async def seed(self) -> DemoResult:
        sport_ids, specialty_ids = await self.reference.ensure()
        await self.uow.commit()
        people = await self.users.ensure(sport_ids, specialty_ids)
        await self.uow.commit()
        actors = people.actors()
        slots_created = await self.slots.ensure(actors.admin_id, actors.doctor_ids)  # commits per doctor
        appointments = await self.appointments.ensure(actors)  # commits itself
        return DemoResult(people.logins, slots_created, appointments)
