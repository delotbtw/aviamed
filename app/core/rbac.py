"""Roles and the permission matrix (docs/03_matrix.md) as data in one place.

Ownership checks ("own", "own specialty", "participating cases") are NOT done here:
they belong to the service layer. The matrix only says which scope a role gets.
"""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    REGISTRAR = "registrar"
    DOCTOR = "doctor"
    ATHLETE = "athlete"
    COACH = "coach"


class Scope(StrEnum):
    FULL = "full"  # ✓
    OWN = "own"  # "свои": only own data
    READ = "read"  # "чтение": view only
    PROXY = "proxy"  # registrar acts on behalf of an athlete
    WARDS = "wards"  # coach: assigned athletes only
    CONCLUDER = "concluder"  # doctor with can_issue_conclusion
    PARTICIPATING = "participating"  # doctor: cases where participates (sports doctor: all)
    OWN_SPECIALTY = "own_specialty"  # doctor: own specialty only
    ISSUED = "issued"  # doctor: only conclusions issued by them


class Action(StrEnum):
    USER_CREATE = "user_create"
    USER_DEACTIVATE = "user_deactivate"
    ATHLETE_REGISTER = "athlete_register"
    PROFILE_EDIT = "profile_edit"
    REFERENCE_READ = "reference_read"
    REFERENCE_WRITE = "reference_write"
    SLOT_CREATE = "slot_create"
    SLOT_VIEW_FREE = "slot_view_free"
    APPOINTMENT_BOOK = "appointment_book"
    APPOINTMENT_CANCEL = "appointment_cancel"
    CASE_OPEN = "case_open"
    ARRIVAL_MARK = "arrival_mark"
    EXAM_RESULT_WRITE = "exam_result_write"
    STRESS_TEST_WRITE = "stress_test_write"
    CONCLUSION_ISSUE = "conclusion_issue"
    EXAM_RESULT_VIEW = "exam_result_view"
    CLEARANCE_STATUS_VIEW = "clearance_status_view"
    CONCLUSION_PDF = "conclusion_pdf"
    AUDIT_VIEW = "audit_view"
    ADMIN_PANEL = "admin_panel"


F, OWN, R = Scope.FULL, Scope.OWN, Scope.READ

# action -> role -> scope. A missing role means "—" (no access).
PERMISSIONS: dict[Action, dict[Role, Scope]] = {
    Action.USER_CREATE: {Role.ADMIN: F},
    Action.USER_DEACTIVATE: {Role.ADMIN: F},
    Action.ATHLETE_REGISTER: {Role.ADMIN: F, Role.REGISTRAR: F},
    Action.PROFILE_EDIT: {Role.ADMIN: F, Role.REGISTRAR: F, Role.DOCTOR: F, Role.ATHLETE: OWN, Role.COACH: F},
    Action.REFERENCE_READ: {Role.ADMIN: F, Role.REGISTRAR: R, Role.DOCTOR: R, Role.ATHLETE: R, Role.COACH: R},
    Action.REFERENCE_WRITE: {Role.ADMIN: F},
    Action.SLOT_CREATE: {Role.ADMIN: F, Role.DOCTOR: OWN},
    Action.SLOT_VIEW_FREE: {Role.ADMIN: F, Role.REGISTRAR: F, Role.DOCTOR: F, Role.ATHLETE: F},
    Action.APPOINTMENT_BOOK: {Role.ADMIN: F, Role.REGISTRAR: Scope.PROXY, Role.ATHLETE: OWN},
    Action.APPOINTMENT_CANCEL: {Role.ADMIN: F, Role.REGISTRAR: F, Role.ATHLETE: OWN},
    Action.CASE_OPEN: {Role.ADMIN: F, Role.REGISTRAR: F},
    Action.ARRIVAL_MARK: {Role.REGISTRAR: F},
    Action.EXAM_RESULT_WRITE: {Role.DOCTOR: Scope.OWN_SPECIALTY},
    Action.STRESS_TEST_WRITE: {Role.DOCTOR: F},
    Action.CONCLUSION_ISSUE: {Role.DOCTOR: Scope.CONCLUDER},
    Action.EXAM_RESULT_VIEW: {Role.DOCTOR: Scope.PARTICIPATING, Role.ATHLETE: OWN},
    Action.CLEARANCE_STATUS_VIEW: {
        Role.ADMIN: F,
        Role.REGISTRAR: F,
        Role.DOCTOR: F,
        Role.ATHLETE: OWN,
        Role.COACH: Scope.WARDS,
    },
    Action.CONCLUSION_PDF: {Role.REGISTRAR: F, Role.DOCTOR: Scope.ISSUED, Role.ATHLETE: OWN},
    Action.AUDIT_VIEW: {Role.ADMIN: F},
    Action.ADMIN_PANEL: {Role.ADMIN: F},
}


def roles_for(action: Action) -> frozenset[Role]:
    """Roles that have any access to the action (scope is checked in services)."""
    return frozenset(PERMISSIONS[action])


def scope_for(action: Action, role: Role) -> Scope | None:
    return PERMISSIONS[action].get(role)
