from pydantic import BaseModel, ConfigDict

from app.models.enums import ExamKind, ProgramCode


class NamedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ExamTypeRead(NamedRead):
    code: str
    specialty_id: int | None
    kind: ExamKind


class ExamProgramRead(NamedRead):
    code: ProgramCode
    validity_months: int
