from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuthorshipMixin, Base, IdMixin, TimestampMixin, enum_col
from app.models.enums import CaseStatus, Decision, ExamResult, ExamStatus, StressProtocol


class MedicalCase(IdMixin, TimestampMixin, AuthorshipMixin, Base):
    __tablename__ = "medical_cases"
    __table_args__ = (
        # One active case per athlete and program.
        Index(
            "uq_medical_cases_active",
            "athlete_id",
            "program_id",
            unique=True,
            postgresql_where=text("status NOT IN ('completed', 'cancelled', 'expired')"),
        ),
    )

    athlete_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("exam_programs.id", ondelete="RESTRICT"))
    status: Mapped[CaseStatus] = mapped_column(
        enum_col(CaseStatus, "case_status"), default=CaseStatus.REGISTERED, index=True
    )
    opened_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[date | None] = mapped_column(Date)
    # Optimistic locking against concurrent edits.
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


class Examination(IdMixin, TimestampMixin, AuthorshipMixin, Base):
    __tablename__ = "examinations"

    case_id: Mapped[int] = mapped_column(ForeignKey("medical_cases.id", ondelete="RESTRICT"), index=True)
    exam_type_id: Mapped[int] = mapped_column(ForeignKey("exam_types.id", ondelete="RESTRICT"))
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id", ondelete="RESTRICT"))
    status: Mapped[ExamStatus] = mapped_column(enum_col(ExamStatus, "exam_status"), default=ExamStatus.PENDING)
    result: Mapped[ExamResult | None] = mapped_column(enum_col(ExamResult, "exam_result"))
    findings: Mapped[str | None] = mapped_column(Text)
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StressTest(IdMixin, TimestampMixin, AuthorshipMixin, Base):
    __tablename__ = "stress_tests"

    examination_id: Mapped[int] = mapped_column(ForeignKey("examinations.id", ondelete="RESTRICT"), unique=True)
    protocol: Mapped[StressProtocol] = mapped_column(enum_col(StressProtocol, "stress_protocol"))
    hr_rest: Mapped[int | None] = mapped_column(SmallInteger)
    hr_peak: Mapped[int | None] = mapped_column(SmallInteger)
    hr_rec_1m: Mapped[int | None] = mapped_column(SmallInteger)
    hr_rec_3m: Mapped[int | None] = mapped_column(SmallInteger)
    bp_before: Mapped[str | None] = mapped_column(String(16))
    bp_after: Mapped[str | None] = mapped_column(String(16))
    spo2_min: Mapped[int | None] = mapped_column(SmallInteger)
    power_w: Mapped[int | None] = mapped_column(SmallInteger)
    duration_s: Mapped[int | None]
    pwc170: Mapped[float | None] = mapped_column(Numeric(7, 2))
    borg_score: Mapped[int | None] = mapped_column(SmallInteger)
    ecg_note: Mapped[str | None] = mapped_column(Text)
    vo2max: Mapped[float | None] = mapped_column(Numeric(5, 1))


class Conclusion(IdMixin, TimestampMixin, AuthorshipMixin, Base):
    __tablename__ = "conclusions"

    number: Mapped[str] = mapped_column(String(64), unique=True)
    # One conclusion per case.
    case_id: Mapped[int] = mapped_column(ForeignKey("medical_cases.id", ondelete="RESTRICT"), unique=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    decision: Mapped[Decision] = mapped_column(enum_col(Decision, "decision"))
    admitted_training: Mapped[bool] = mapped_column(Boolean, default=False)
    admitted_competitions: Mapped[bool] = mapped_column(Boolean, default=False)
    admitted_physical_events: Mapped[bool] = mapped_column(Boolean, default=False)
    admitted_gto: Mapped[bool] = mapped_column(Boolean, default=False)
    event_name: Mapped[str | None] = mapped_column(String(255))
    sport_discipline: Mapped[str | None] = mapped_column(String(255))
    has_restrictions: Mapped[bool] = mapped_column(Boolean, default=False)
    restrictions_term: Mapped[str | None] = mapped_column(String(128))
    restrictions: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[date] = mapped_column(Date)
