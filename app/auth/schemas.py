from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.core.validators import PASSWORD_MAX, NormalizedEmail, StrictModel, check_password_policy


class LoginRequest(StrictModel):
    email: NormalizedEmail
    password: Annotated[str, Field(max_length=PASSWORD_MAX)]  # bounds argon2 input size


class RefreshRequest(StrictModel):
    refresh_token: str


class ChangePasswordRequest(StrictModel):
    old_password: Annotated[str, Field(max_length=PASSWORD_MAX)]
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _policy(cls, v: str) -> str:
        return check_password_policy(v)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
