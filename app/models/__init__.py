"""Import all models so that Base.metadata is complete (Alembic, SQLAdmin)."""

from app.models.base import Base
from app.models.medical import Conclusion, Examination, MedicalCase, StressTest
from app.models.reference import ExamProgram, ExamProgramItem, ExamType, Specialty, Sport
from app.models.schedule import Appointment, Slot
from app.models.system import AuditLog, Consent, RefreshToken, StatusHistory
from app.models.user import AthleteProfile, CoachProfile, DoctorProfile, StaffProfile, User

__all__ = [
    "Appointment",
    "AthleteProfile",
    "AuditLog",
    "Base",
    "CoachProfile",
    "Conclusion",
    "Consent",
    "DoctorProfile",
    "ExamProgram",
    "ExamProgramItem",
    "ExamType",
    "Examination",
    "MedicalCase",
    "RefreshToken",
    "Slot",
    "Specialty",
    "Sport",
    "StaffProfile",
    "StatusHistory",
    "StressTest",
    "User",
]
