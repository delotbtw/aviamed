from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference import ExamProgram, ExamType, Specialty, Sport
from app.repositories.reference import (
    ExamProgramRepository,
    ExamTypeRepository,
    SpecialtyRepository,
    SportRepository,
)


class ReferenceService:
    """Read access is implemented; admin editing is a TODO (also available via SQLAdmin)."""

    def __init__(self, session: AsyncSession) -> None:
        self.sports = SportRepository(session)
        self.specialties = SpecialtyRepository(session)
        self.exam_types = ExamTypeRepository(session)
        self.programs = ExamProgramRepository(session)

    async def sports_list(self) -> list[Sport]:
        return list(await self.sports.list())

    async def specialties_list(self) -> list[Specialty]:
        return list(await self.specialties.list())

    async def exam_types_list(self) -> list[ExamType]:
        return list(await self.exam_types.list())

    async def programs_list(self) -> list[ExamProgram]:
        return list(await self.programs.list())
