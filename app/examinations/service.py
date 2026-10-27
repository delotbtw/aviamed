from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_implemented
from app.examinations.schemas import ExamResultIn, StressTestIn
from app.models.medical import Examination
from app.models.user import User
from app.repositories.medical import ExaminationRepository, StressTestRepository


class ExaminationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.exams = ExaminationRepository(session)
        self.stress_tests = StressTestRepository(session)

    async def get(self, exam_id: int, actor: User) -> Examination:
        # TODO: doctor sees cases where participates (sports doctor: all), athlete own.
        raise not_implemented()

    async def submit_result(self, exam_id: int, data: ExamResultIn, actor: User) -> Examination:
        # TODO: own specialty check; pending -> done; appointment arrived -> done; CaseService.recalc_progress.
        raise not_implemented()

    async def submit_stress_test(self, exam_id: int, data: StressTestIn, actor: User) -> Examination:
        raise not_implemented()
