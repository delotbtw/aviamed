from sqlalchemy.exc import IntegrityError

from app.audit.service import AuditService
from app.auth.tokens import TokenService
from app.core.exceptions import Conflict, NotFound, PermissionDenied
from app.core.rbac import Action, Role, Scope, scope_for
from app.core.uow import UnitOfWork
from app.models.system import Consent
from app.models.user import AthleteProfile, User
from app.repositories.base import violated_constraint
from app.repositories.system import ConsentRepository
from app.repositories.user import AthleteProfileRepository, UserRepository
from app.users.accounts import AccountCreator, ReferenceValidator
from app.users.profiles import ProfileCreator
from app.users.schemas import AthleteRegister, ProfileUpdate, UserCreate

CONSENT_TYPE = "personal_data_health"
CONSENT_NUMBER_CONSTRAINT = "uq_consents_type_paper_number_active"
_NAME_FIELDS = frozenset({"first_name", "last_name", "middle_name"})


class UserService:
    """Staff accounts: create and edit own profile."""

    def __init__(
        self,
        uow: UnitOfWork,
        accounts: AccountCreator,
        profile_creators: dict[Role, ProfileCreator],
        audit: AuditService,
    ) -> None:
        self.uow = uow
        self.accounts = accounts
        self.profile_creators = profile_creators
        self.audit = audit

    async def create_user(self, data: UserCreate, actor: User, ip: str | None = None) -> User:
        creator = self.profile_creators[data.role]  # athletes are rejected by the schema
        await creator.validate(data)
        user = await self.accounts.create(
            email=data.email,
            password=data.password,
            role=data.role,
            last_name=data.last_name,
            first_name=data.first_name,
            middle_name=data.middle_name,
            phone=data.phone,
        )
        await creator.create(user, data)
        await self.audit.log(user_id=actor.id, action="user_create", entity_type="user", entity_id=user.id, ip=ip)
        await self.uow.commit()
        return user

    async def update_profile(self, user: User, data: ProfileUpdate, ip: str | None = None) -> User:
        changes = data.model_dump(exclude_unset=True)
        if scope_for(Action.PROFILE_EDIT, user.role) is Scope.OWN and _NAME_FIELDS & changes.keys():
            raise PermissionDenied("Name is changed by the registrar")
        for field, value in changes.items():
            setattr(user, field, value)
        await self.audit.log(user_id=user.id, action="profile_update", entity_type="user", entity_id=user.id, ip=ip)
        await self.uow.commit()
        return user


class AccountLifecycleService:
    """Account state changes."""

    def __init__(self, uow: UnitOfWork, users: UserRepository, tokens: TokenService, audit: AuditService) -> None:
        self.uow = uow
        self.users = users
        self.tokens = tokens
        self.audit = audit

    async def deactivate(self, user_id: int, actor: User, ip: str | None = None) -> None:
        if user_id == actor.id:
            raise Conflict("Administrator cannot deactivate themselves")
        target = await self.users.get_for_update(user_id)
        if target is None:
            raise NotFound("User not found")
        if not target.is_active:
            return  # idempotent: no second audit record
        target.is_active = False
        revoked = await self.tokens.revoke_all(target.id)
        await self.audit.log(user_id=actor.id, action="user_deactivate", entity_type="user", entity_id=target.id, ip=ip)
        await self.uow.commit()
        await self.tokens.blacklist_revoked(revoked)


class AthleteRegistrationService:
    """Athlete account + profile + paper consent in one transaction."""

    def __init__(
        self,
        uow: UnitOfWork,
        accounts: AccountCreator,
        references: ReferenceValidator,
        athletes: AthleteProfileRepository,
        consents: ConsentRepository,
        audit: AuditService,
    ) -> None:
        self.uow = uow
        self.accounts = accounts
        self.references = references
        self.athletes = athletes
        self.consents = consents
        self.audit = audit

    async def register(self, data: AthleteRegister, actor: User, ip: str | None = None) -> User:
        await self.references.sport(data.sport_id)
        await self.references.coach(data.coach_id)
        if await self.consents.paper_number_taken(CONSENT_TYPE, data.consent_paper_number):
            raise Conflict("Consent paper number is already used")

        user = await self.accounts.create(
            email=data.email,
            password=data.password,
            role=Role.ATHLETE,
            last_name=data.last_name,
            first_name=data.first_name,
            middle_name=data.middle_name,
            phone=data.phone,
        )
        await self.athletes.add(
            AthleteProfile(
                user_id=user.id,
                birth_date=data.birth_date,
                sex=data.sex,
                faculty=data.faculty,
                study_group=data.study_group,
                sport_id=data.sport_id,
                training_stage=data.training_stage,
                registry_number=data.registry_number,
                coach_id=data.coach_id,
            )
        )
        try:
            consent = await self.consents.add(
                Consent(
                    user_id=user.id,
                    consent_type=CONSENT_TYPE,
                    paper_number=data.consent_paper_number,
                    signed_at=data.consent_signed_at,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
        except IntegrityError as e:  # concurrent registration with the same paper number won the race
            if violated_constraint(e) != CONSENT_NUMBER_CONSTRAINT:
                raise
            await self.uow.rollback()  # undo user + profile too; the session is unusable after a failed flush
            raise Conflict("Consent paper number is already used") from None
        await self.audit.log(user_id=actor.id, action="athlete_register", entity_type="user", entity_id=user.id, ip=ip)
        await self.audit.log(
            user_id=actor.id, action="consent_create", entity_type="consent", entity_id=consent.id, ip=ip
        )
        await self.uow.commit()
        return user
