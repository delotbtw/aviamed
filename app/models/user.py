from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.rbac import Role
from app.models.base import Base, IdMixin, TimestampMixin, enum_col
from app.models.enums import Sex, TrainingStage


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(enum_col(Role, "user_role"), index=True)
    last_name: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(32))
    # Users are never deleted physically, only deactivated.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    athlete_profile: Mapped["AthleteProfile | None"] = relationship(
        back_populates="user", foreign_keys="AthleteProfile.user_id", uselist=False
    )
    coach_profile: Mapped["CoachProfile | None"] = relationship(back_populates="user", uselist=False)
    doctor_profile: Mapped["DoctorProfile | None"] = relationship(back_populates="user", uselist=False)
    staff_profile: Mapped["StaffProfile | None"] = relationship(back_populates="user", uselist=False)


class AthleteProfile(TimestampMixin, Base):
    __tablename__ = "athlete_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    birth_date: Mapped[date] = mapped_column(Date)
    sex: Mapped[Sex] = mapped_column(enum_col(Sex, "sex"))
    faculty: Mapped[str | None] = mapped_column(String(255))
    study_group: Mapped[str | None] = mapped_column(String(64))
    sport_id: Mapped[int | None] = mapped_column(ForeignKey("sports.id", ondelete="RESTRICT"))
    training_stage: Mapped[TrainingStage | None] = mapped_column(enum_col(TrainingStage, "training_stage"))
    registry_number: Mapped[str | None] = mapped_column(String(64))
    health_group: Mapped[int | None]  # I-IV stored as 1..4
    coach_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)

    user: Mapped[User] = relationship(back_populates="athlete_profile", foreign_keys=[user_id])


class CoachProfile(TimestampMixin, Base):
    __tablename__ = "coach_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    sport_id: Mapped[int | None] = mapped_column(ForeignKey("sports.id", ondelete="RESTRICT"))

    user: Mapped[User] = relationship(back_populates="coach_profile")


class DoctorProfile(TimestampMixin, Base):
    __tablename__ = "doctor_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    specialty_id: Mapped[int] = mapped_column(ForeignKey("specialties.id", ondelete="RESTRICT"))
    cabinet: Mapped[str | None] = mapped_column(String(32))
    can_issue_conclusion: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    user: Mapped[User] = relationship(back_populates="doctor_profile")


class StaffProfile(TimestampMixin, Base):
    __tablename__ = "staff_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[str | None] = mapped_column(String(128))
    workplace: Mapped[str | None] = mapped_column(String(128))

    user: Mapped[User] = relationship(back_populates="staff_profile")
