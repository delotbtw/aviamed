from sqlalchemy import Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, enum_col
from app.models.enums import ExamKind, ProgramCode


class Sport(IdMixin, TimestampMixin, Base):
    __tablename__ = "sports"

    name: Mapped[str] = mapped_column(String(255), unique=True)


class Specialty(IdMixin, TimestampMixin, Base):
    __tablename__ = "specialties"

    name: Mapped[str] = mapped_column(String(255), unique=True)


class ExamType(IdMixin, TimestampMixin, Base):
    __tablename__ = "exam_types"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    specialty_id: Mapped[int | None] = mapped_column(ForeignKey("specialties.id", ondelete="RESTRICT"))
    kind: Mapped[ExamKind] = mapped_column(enum_col(ExamKind, "exam_kind"))


class ExamProgram(IdMixin, TimestampMixin, Base):
    __tablename__ = "exam_programs"

    code: Mapped[ProgramCode] = mapped_column(enum_col(ProgramCode, "program_code"), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    validity_months: Mapped[int] = mapped_column(SmallInteger)


class ExamProgramItem(TimestampMixin, Base):
    __tablename__ = "exam_program_items"

    program_id: Mapped[int] = mapped_column(ForeignKey("exam_programs.id", ondelete="CASCADE"), primary_key=True)
    exam_type_id: Mapped[int] = mapped_column(ForeignKey("exam_types.id", ondelete="RESTRICT"), primary_key=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
