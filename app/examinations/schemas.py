from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ExamResult, ExamStatus, StressProtocol


class ExamResultIn(BaseModel):
    result: ExamResult
    findings: str | None = None


class StressTestIn(BaseModel):
    protocol: StressProtocol
    hr_rest: int | None = None
    hr_peak: int | None = None
    hr_rec_1m: int | None = None
    hr_rec_3m: int | None = None
    bp_before: str | None = None
    bp_after: str | None = None
    spo2_min: int | None = None
    power_w: int | None = None
    duration_s: int | None = None
    pwc170: float | None = None
    borg_score: int | None = None
    ecg_note: str | None = None
    vo2max: float | None = None


class ExaminationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    exam_type_id: int
    doctor_id: int | None
    status: ExamStatus
    result: ExamResult | None
    findings: str | None
    performed_at: datetime | None
