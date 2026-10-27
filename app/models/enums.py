from enum import StrEnum


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class TrainingStage(StrEnum):
    # docs/06 section 2: mass/student sport, training (specialization) stage,
    # improvement of sports mastery, higher mastery. Last two are outside the MVP programs.
    MASS = "mass"
    TRAINING = "training"
    IMPROVEMENT = "improvement"
    HIGHER_MASTERY = "higher_mastery"


class ExamKind(StrEnum):
    VISIT = "visit"
    LAB = "lab"
    FUNCTIONAL = "functional"
    STRESS_TEST = "stress_test"


class CaseStatus(StrEnum):
    REGISTERED = "registered"
    IN_PROGRESS = "in_progress"
    AWAITING_CONCLUSION = "awaiting_conclusion"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    ARRIVED = "arrived"
    DONE = "done"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class SlotStatus(StrEnum):
    FREE = "free"
    BOOKED = "booked"
    CLOSED = "closed"


class ExamStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"


class ExamResult(StrEnum):
    NORMAL = "normal"
    DEVIATION = "deviation"
    CONTRAINDICATION = "contraindication"


class StressProtocol(StrEnum):
    # docs/06 section 5 (order 484n, appendix 1, section II). MVP needs only one or two of them.
    ERGOMETRY_GAS = "ergometry_gas"  # ergometry with gas analysis
    PWC170_ECG = "pwc170_ecg"  # PWC170 under ECG control
    PWC170 = "pwc170"
    ECG_RUN_2MIN = "ecg_run_2min"  # ECG with load: running in place for 2 minutes
    ECG_SQUATS_20 = "ecg_squats_20"  # ECG with load: 20 squats in 30 seconds
    LETUNOV = "letunov"
    RUFFIER = "ruffier"  # 30 squats in 45 seconds


class Decision(StrEnum):
    ADMITTED = "admitted"
    NOT_ADMITTED = "not_admitted"
    REEXAMINATION = "reexamination"


class ProgramCode(StrEnum):
    BASE = "base"
    UMO = "umo"
