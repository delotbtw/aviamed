"""SQLAdmin: admin only. Bypasses the service layer, so working tables are read-only."""

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request

from app.core.access_tokens import AccessTokenService
from app.core.exceptions import AuthenticationFailed
from app.core.rbac import Role
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
    def __init__(self, secret_key: str, access_tokens: AccessTokenService) -> None:
        super().__init__(secret_key=secret_key)
        self.access_tokens = access_tokens

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
            return self.access_tokens.parse(token).role == Role.ADMIN
        except AuthenticationFailed:
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


def setup_admin(app: FastAPI, engine: AsyncEngine, secret_key: str, access_tokens: AccessTokenService) -> Admin:
    admin = Admin(
        app,
        engine,
        base_url="/admin",
        authentication_backend=AdminAuth(secret_key, access_tokens),
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
