from sqlalchemy import select

from app.models.medical import Conclusion, Examination, MedicalCase, StressTest
from app.repositories.base import BaseRepository


class MedicalCaseRepository(BaseRepository[MedicalCase]):
    model = MedicalCase

    async def list_by_athlete(self, athlete_id: int) -> list[MedicalCase]:
        result = await self.session.scalars(select(MedicalCase).where(MedicalCase.athlete_id == athlete_id))
        return list(result)


class ExaminationRepository(BaseRepository[Examination]):
    model = Examination

    async def list_by_case(self, case_id: int) -> list[Examination]:
        result = await self.session.scalars(select(Examination).where(Examination.case_id == case_id))
        return list(result)


class StressTestRepository(BaseRepository[StressTest]):
    model = StressTest


class ConclusionRepository(BaseRepository[Conclusion]):
    model = Conclusion

    async def get_by_case(self, case_id: int) -> Conclusion | None:
        return await self.session.scalar(select(Conclusion).where(Conclusion.case_id == case_id))
