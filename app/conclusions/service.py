from sqlalchemy.ext.asyncio import AsyncSession

from app.conclusions.schemas import ClearanceStatus, ConclusionCreate
from app.core.errors import not_implemented
from app.models.medical import Conclusion
from app.models.user import User
from app.repositories.medical import ConclusionRepository, MedicalCaseRepository


class ConclusionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conclusions = ConclusionRepository(session)
        self.cases = MedicalCaseRepository(session)

    async def issue(self, data: ConclusionCreate, actor: User) -> Conclusion:
        # TODO: can_issue_conclusion check, case awaiting_conclusion, all required exams done,
        # number generation, valid_until <= 1 year, awaiting_conclusion -> completed, audit.
        raise not_implemented()

    async def clearance_status(self, case_id: int, actor: User) -> ClearanceStatus:
        # TODO: coach only for wards (athlete_profiles.coach_id), athlete own.
        raise not_implemented()

    async def render_pdf(self, case_id: int, actor: User) -> bytes:
        # TODO: Jinja template (app/templates/conclusion.html) -> WeasyPrint, run in a thread
        # (weasyprint is sync/CPU-bound); strict rate limit; audit the download.
        raise not_implemented()
