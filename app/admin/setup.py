"""SQLAdmin: admin only. Bypasses the service layer, so working tables are read-only."""

import jwt
from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.core.config import get_settings
from app.core.db import engine
from app.core.rbac import Role
from app.core.security import decode_token
from app.models import (
    AuditLog,
    Conclusion,
    Examination,
    ExamProgram,
    ExamType,
    MedicalCase,
    Specialty,
    Sport,
    User,
)


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        # TODO: login form -> verify credentials -> put access token into the session/cookie.
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        token = request.cookies.get("access_token") or request.session.get("token")
        if not token:
            return False
        try:
            return decode_token(token).get("role") == Role.ADMIN
        except jwt.PyJWTError:
            return False


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.email, User.role, User.last_name, User.is_active]
    column_details_exclude_list = [User.password_hash]
    form_excluded_columns = [User.password_hash]  # TODO: password change goes through the service
    can_delete = False  # users are deactivated, not deleted


class SportAdmin(ModelView, model=Sport):
    column_list = [Sport.id, Sport.name]


class SpecialtyAdmin(ModelView, model=Specialty):
    column_list = [Specialty.id, Specialty.name]


class ExamTypeAdmin(ModelView, model=ExamType):
    column_list = [ExamType.id, ExamType.code, ExamType.name, ExamType.kind]


class ExamProgramAdmin(ModelView, model=ExamProgram):
    column_list = [ExamProgram.id, ExamProgram.code, ExamProgram.name]


class _ReadOnly:
    can_create = False
    can_edit = False
    can_delete = False


class MedicalCaseAdmin(_ReadOnly, ModelView, model=MedicalCase):
    column_list = [MedicalCase.id, MedicalCase.athlete_id, MedicalCase.status]


class ExaminationAdmin(_ReadOnly, ModelView, model=Examination):
    column_list = [Examination.id, Examination.case_id, Examination.status]


class ConclusionAdmin(_ReadOnly, ModelView, model=Conclusion):
    column_list = [Conclusion.id, Conclusion.number, Conclusion.case_id]


class AuditLogAdmin(_ReadOnly, ModelView, model=AuditLog):
    column_list = [AuditLog.id, AuditLog.user_id, AuditLog.action, AuditLog.created_at]


def setup_admin(app: FastAPI) -> Admin:
    admin = Admin(
        app,
        engine,
        base_url="/admin",
        authentication_backend=AdminAuth(secret_key=get_settings().secret_key),
    )
    for view in (
        UserAdmin,
        SportAdmin,
        SpecialtyAdmin,
        ExamTypeAdmin,
        ExamProgramAdmin,
        MedicalCaseAdmin,
        ExaminationAdmin,
        ConclusionAdmin,
        AuditLogAdmin,
    ):
        admin.add_view(view)
    # TODO: write admin actions to audit_log (on_model_change hooks).
    return admin
