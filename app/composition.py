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
from app.core.deps import AccessTokensDep, RedisDep, SessionDep, SettingsDep, UnitOfWorkDep, UserRepoDep
from app.core.rbac import Role
from app.core.security import Argon2PasswordHasher, PasswordHasher
from app.repositories.reference import SpecialtyRepository, SportRepository
from app.repositories.system import AuditLogRepository, ConsentRepository, RefreshTokenRepository
from app.repositories.user import (
    AthleteProfileRepository,
    CoachProfileRepository,
    DoctorProfileRepository,
    StaffProfileRepository,
)
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
