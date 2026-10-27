from datetime import date
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints, field_validator, model_validator

from app.core.rbac import Role
from app.core.validators import Name, NormalizedEmail, Phone, StrictModel, check_password_policy
from app.models.enums import Sex, TrainingStage

MAX_AGE_YEARS = 120

PaperNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: Role
    last_name: str
    first_name: str
    middle_name: str | None
    phone: str | None
    is_active: bool


class _NewAccount(StrictModel):
    """Fields shared by every account created by staff."""

    email: NormalizedEmail
    password: str
    last_name: Name
    first_name: Name
    middle_name: Name | None = None
    phone: Phone | None = None

    @model_validator(mode="after")
    def _password_policy(self) -> Self:
        check_password_policy(self.password, self.email)
        return self


# Profile fields allowed per role of the created user.
_DOCTOR_FIELDS = frozenset({"specialty_id", "cabinet", "can_issue_conclusion"})
_STAFF_FIELDS = frozenset({"position", "workplace"})
_COACH_FIELDS = frozenset({"sport_id"})
_ROLE_FIELDS: dict[Role, frozenset[str]] = {
    Role.DOCTOR: _DOCTOR_FIELDS,
    Role.REGISTRAR: _STAFF_FIELDS,
    Role.ADMIN: _STAFF_FIELDS,
    Role.COACH: _COACH_FIELDS,
}


class UserCreate(_NewAccount):
    role: Role
    # doctor
    specialty_id: int | None = None
    cabinet: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None
    can_issue_conclusion: bool = False
    # registrar, admin
    position: Annotated[str, StringConstraints(strip_whitespace=True, max_length=128)] | None = None
    workplace: Annotated[str, StringConstraints(strip_whitespace=True, max_length=128)] | None = None
    # coach
    sport_id: int | None = None

    @model_validator(mode="after")
    def _role_profile(self) -> Self:
        if self.role not in _ROLE_FIELDS:
            raise ValueError("Athletes are registered via /users/athletes")
        allowed = _ROLE_FIELDS[self.role]
        foreign = (_DOCTOR_FIELDS | _STAFF_FIELDS | _COACH_FIELDS) & self.model_fields_set - allowed
        if foreign:
            raise ValueError(f"Fields not allowed for role {self.role.value}: {', '.join(sorted(foreign))}")
        if self.role is Role.DOCTOR and self.specialty_id is None:
            raise ValueError("specialty_id is required for a doctor")
        return self


class AthleteRegister(_NewAccount):
    """Registration by registrar at a personal visit, incl. paper consent number."""

    birth_date: date
    sex: Sex
    sport_id: int | None = None
    coach_id: int | None = None
    faculty: ShortText | None = None
    study_group: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None
    training_stage: TrainingStage | None = None
    registry_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None
    consent_paper_number: PaperNumber
    consent_signed_at: date

    @field_validator("birth_date")
    @classmethod
    def _birth_date_range(cls, v: date) -> date:
        today = date.today()
        if v > today:
            raise ValueError("birth_date must not be in the future")
        if v.year < today.year - MAX_AGE_YEARS or (
            v.year == today.year - MAX_AGE_YEARS and (v.month, v.day) < (today.month, today.day)
        ):
            raise ValueError(f"birth_date must not be older than {MAX_AGE_YEARS} years")
        return v

    @field_validator("consent_signed_at")
    @classmethod
    def _consent_not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("consent_signed_at must not be in the future")
        return v


class ProfileUpdate(StrictModel):
    phone: Phone | None = None
    first_name: Name | None = None
    last_name: Name | None = None
    middle_name: Name | None = None

    @model_validator(mode="after")
    def _non_empty(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        for field in ("first_name", "last_name"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self
