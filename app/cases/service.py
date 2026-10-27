from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.schemas import CaseCreate
from app.core.errors import not_implemented
from app.models.medical import MedicalCase
from app.models.user import User
from app.repositories.medical import MedicalCaseRepository


class CaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cases = MedicalCaseRepository(session)

    async def open_case(self, data: CaseCreate, actor: User) -> MedicalCase:
        # TODO: one active case per athlete+program; create pending examinations from program items.
        raise not_implemented()

    async def list_for(self, actor: User) -> list[MedicalCase]:
        # TODO: scope by role (registrar/admin all, athlete own, coach wards).
        raise not_implemented()

    async def cancel(self, case_id: int, actor: User) -> None:
        # TODO: services.status.change_status with CASE_TRANSITIONS.
        raise not_implemented()

    async def recalc_progress(self, case_id: int) -> None:
        # TODO: all required items done -> in_progress -> awaiting_conclusion (system actor).
        raise not_implemented()
