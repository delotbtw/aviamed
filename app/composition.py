"""Composition root: builds feature services and injects their collaborators (repositories, Redis, hasher, ...).

Routers and page handlers import the `*Dep` annotations from here; services never construct their own dependencies.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.audit.service import AuditService
from app.auth.rate_limit import AttemptLimiter, RedisAttemptLimiter
from app.auth.service import AuthService
from app.auth.tokens import TokenBlacklist, TokenService
from app.core.deps import (
    AccessTokensDep,
    CalendarDep,
    ClockDep,
    RedisDep,
    SessionDep,
    SettingsDep,
    UnitOfWorkDep,
    UserRepoDep,
)
from app.core.rbac import Role
from app.core.security import Argon2PasswordHasher, PasswordHasher
from app.repositories.medical import MedicalCaseRepository
from app.repositories.reference import SpecialtyRepository, SportRepository
from app.repositories.schedule import AppointmentRepository, ScheduleReadRepository, SlotRepository
from app.repositories.system import (
    AuditLogRepository,
    ConsentRepository,
    RefreshTokenRepository,
    StatusHistoryRepository,
)
from app.repositories.user import (
    AthleteProfileRepository,
    CoachProfileRepository,
    DoctorProfileRepository,
    StaffProfileRepository,
)
from app.schedule.attendance import AttendanceService
from app.schedule.booking import BookingService
from app.schedule.planning import SlotPlanner
from app.schedule.policy import BookingPolicy
from app.schedule.queries import ScheduleDirectory, ScheduleQueryService
from app.schedule.slots import SlotService
from app.services.status import StatusChanger
from app.users.accounts import AccountCreator, ReferenceValidator
from app.users.profiles import CoachProfileCreator, DoctorProfileCreator, ProfileCreator, StaffProfileCreator
from app.users.service import AccountLifecycleService, AthleteRegistrationService, UserService

# --------------------------------------------------------------------------- infrastructure


@lru_cache
def get_password_hasher() -> PasswordHasher:
    """Cached: the argon2 dummy hash is computed once."""
    return Argon2PasswordHasher()


HasherDep = Annotated[PasswordHasher, Depends(get_password_hasher)]


def get_audit_repo(session: SessionDep) -> AuditLogRepository:
    return AuditLogRepository(session)


AuditRepoDep = Annotated[AuditLogRepository, Depends(get_audit_repo)]


def get_audit_service(repo: AuditRepoDep) -> AuditService:
    return AuditService(repo)


AuditDep = Annotated[AuditService, Depends(get_audit_service)]

# --------------------------------------------------------------------------- auth


def get_token_service(
    session: SessionDep, redis: RedisDep, settings: SettingsDep, access_tokens: AccessTokensDep
) -> TokenService:
    return TokenService(
        RefreshTokenRepository(session),
        TokenBlacklist(redis),
        access_tokens,
        refresh_ttl_days=settings.refresh_token_ttl_days,
    )


TokenServiceDep = Annotated[TokenService, Depends(get_token_service)]


def get_attempt_limiter(redis: RedisDep, settings: SettingsDep) -> AttemptLimiter:
    return RedisAttemptLimiter(
        redis,
        max_attempts=settings.login_max_attempts,
        max_attempts_ip=settings.login_max_attempts_ip,
        window_s=settings.login_window_s,
    )


def get_auth_service(
    uow: UnitOfWorkDep,
    users: UserRepoDep,
    tokens: TokenServiceDep,
    limiter: Annotated[AttemptLimiter, Depends(get_attempt_limiter)],
    hasher: HasherDep,
    audit: AuditDep,
) -> AuthService:
    return AuthService(uow, users, tokens, limiter, hasher, audit)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

# --------------------------------------------------------------------------- users


def get_account_creator(users: UserRepoDep, hasher: HasherDep, uow: UnitOfWorkDep) -> AccountCreator:
    return AccountCreator(users, hasher, uow)


def get_reference_validator(session: SessionDep, users: UserRepoDep) -> ReferenceValidator:
    return ReferenceValidator(SportRepository(session), SpecialtyRepository(session), users)


AccountCreatorDep = Annotated[AccountCreator, Depends(get_account_creator)]
ReferenceValidatorDep = Annotated[ReferenceValidator, Depends(get_reference_validator)]


def get_profile_creators(session: SessionDep, references: ReferenceValidatorDep) -> dict[Role, ProfileCreator]:
    staff = StaffProfileCreator(StaffProfileRepository(session))
    return {
        Role.DOCTOR: DoctorProfileCreator(DoctorProfileRepository(session), references),
        Role.COACH: CoachProfileCreator(CoachProfileRepository(session), references),
        Role.REGISTRAR: staff,
        Role.ADMIN: staff,
    }


def get_user_service(
    uow: UnitOfWorkDep,
    accounts: AccountCreatorDep,
    profile_creators: Annotated[dict[Role, ProfileCreator], Depends(get_profile_creators)],
    audit: AuditDep,
) -> UserService:
    return UserService(uow, accounts, profile_creators, audit)


def get_athlete_registration_service(
    session: SessionDep,
    uow: UnitOfWorkDep,
    accounts: AccountCreatorDep,
    references: ReferenceValidatorDep,
    audit: AuditDep,
) -> AthleteRegistrationService:
    return AthleteRegistrationService(
        uow, accounts, references, AthleteProfileRepository(session), ConsentRepository(session), audit
    )


def get_account_lifecycle_service(
    uow: UnitOfWorkDep, users: UserRepoDep, tokens: TokenServiceDep, audit: AuditDep
) -> AccountLifecycleService:
    return AccountLifecycleService(uow, users, tokens, audit)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
AthleteRegistrationDep = Annotated[AthleteRegistrationService, Depends(get_athlete_registration_service)]
AccountLifecycleDep = Annotated[AccountLifecycleService, Depends(get_account_lifecycle_service)]

# --------------------------------------------------------------------------- schedule


def get_status_changer(session: SessionDep) -> StatusChanger:
    return StatusChanger(StatusHistoryRepository(session))


StatusChangerDep = Annotated[StatusChanger, Depends(get_status_changer)]


def get_slot_planner(settings: SettingsDep, clock: ClockDep) -> SlotPlanner:
    return SlotPlanner(settings, clock)


def get_slot_repo(session: SessionDep) -> SlotRepository:
    return SlotRepository(session)


def get_appointment_repo(session: SessionDep) -> AppointmentRepository:
    return AppointmentRepository(session)


def get_case_repo(session: SessionDep) -> MedicalCaseRepository:
    return MedicalCaseRepository(session)


SlotRepoDep = Annotated[SlotRepository, Depends(get_slot_repo)]
AppointmentRepoDep = Annotated[AppointmentRepository, Depends(get_appointment_repo)]
CaseRepoDep = Annotated[MedicalCaseRepository, Depends(get_case_repo)]


def get_slot_service(
    uow: UnitOfWorkDep,
    users: UserRepoDep,
    slots: SlotRepoDep,
    status_changer: StatusChangerDep,
    audit: AuditDep,
    planner: Annotated[SlotPlanner, Depends(get_slot_planner)],
    clock: ClockDep,
    settings: SettingsDep,
) -> SlotService:
    return SlotService(uow, users, slots, status_changer, audit, planner, clock, settings)


def get_booking_policy(
    users: UserRepoDep,
    appointments: AppointmentRepoDep,
    cases: CaseRepoDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> BookingPolicy:
    return BookingPolicy(users, appointments, cases, clock, settings)


def get_booking_service(
    uow: UnitOfWorkDep,
    users: UserRepoDep,
    slots: SlotRepoDep,
    appointments: AppointmentRepoDep,
    policy: Annotated[BookingPolicy, Depends(get_booking_policy)],
    status_changer: StatusChangerDep,
    audit: AuditDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> BookingService:
    return BookingService(uow, users, slots, appointments, policy, status_changer, audit, clock, settings)


def get_attendance_service(
    uow: UnitOfWorkDep,
    slots: SlotRepoDep,
    appointments: AppointmentRepoDep,
    cases: CaseRepoDep,
    status_changer: StatusChangerDep,
    audit: AuditDep,
    clock: ClockDep,
    calendar: CalendarDep,
    settings: SettingsDep,
) -> AttendanceService:
    return AttendanceService(uow, slots, appointments, cases, status_changer, audit, clock, calendar, settings)


def get_schedule_reader(session: SessionDep) -> ScheduleReadRepository:
    return ScheduleReadRepository(session)


ScheduleReaderDep = Annotated[ScheduleReadRepository, Depends(get_schedule_reader)]


def get_schedule_queries(
    reader: ScheduleReaderDep, clock: ClockDep, calendar: CalendarDep, settings: SettingsDep
) -> ScheduleQueryService:
    return ScheduleQueryService(reader, clock, calendar, settings)


def get_schedule_directory(reader: ScheduleReaderDep) -> ScheduleDirectory:
    return ScheduleDirectory(reader)


SlotServiceDep = Annotated[SlotService, Depends(get_slot_service)]
BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]
AttendanceServiceDep = Annotated[AttendanceService, Depends(get_attendance_service)]
ScheduleQueriesDep = Annotated[ScheduleQueryService, Depends(get_schedule_queries)]
ScheduleDirectoryDep = Annotated[ScheduleDirectory, Depends(get_schedule_directory)]
