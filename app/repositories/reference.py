from app.models.reference import ExamProgram, ExamProgramItem, ExamType, Specialty, Sport
from app.repositories.base import BaseRepository


class SportRepository(BaseRepository[Sport]):
    model = Sport


class SpecialtyRepository(BaseRepository[Specialty]):
    model = Specialty


class ExamTypeRepository(BaseRepository[ExamType]):
    model = ExamType


class ExamProgramRepository(BaseRepository[ExamProgram]):
    model = ExamProgram


class ExamProgramItemRepository(BaseRepository[ExamProgramItem]):
    model = ExamProgramItem
