from sqlalchemy import select

from app.models.reference import ExamProgram, ExamProgramItem, ExamType, Specialty, Sport
from app.repositories.base import BaseRepository


class SportRepository(BaseRepository[Sport]):
    model = Sport

    async def get_by_name(self, name: str) -> Sport | None:
        return await self.session.scalar(select(Sport).where(Sport.name == name))


class SpecialtyRepository(BaseRepository[Specialty]):
    model = Specialty

    async def get_by_name(self, name: str) -> Specialty | None:
        return await self.session.scalar(select(Specialty).where(Specialty.name == name))


class ExamTypeRepository(BaseRepository[ExamType]):
    model = ExamType


class ExamProgramRepository(BaseRepository[ExamProgram]):
    model = ExamProgram


class ExamProgramItemRepository(BaseRepository[ExamProgramItem]):
    model = ExamProgramItem
