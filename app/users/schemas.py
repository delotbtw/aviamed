from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr

from app.core.rbac import Role
from app.models.enums import Sex


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


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: Role
    last_name: str
    first_name: str
    middle_name: str | None = None
    phone: str | None = None


class AthleteRegister(BaseModel):
    """Registration by registrar at a personal visit, incl. paper consent number."""

    email: EmailStr
    password: str
    last_name: str
    first_name: str
    middle_name: str | None = None
    phone: str | None = None
    birth_date: date
    sex: Sex
    sport_id: int | None = None
    coach_id: int | None = None
    consent_paper_number: str
    consent_signed_at: date


class ProfileUpdate(BaseModel):
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
