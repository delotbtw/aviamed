"""Domain errors of the schedule. The `detail` texts are part of the API contract (spec section 3)."""

from app.core.exceptions import Conflict

SLOT_TAKEN = "Slot is already taken"
SLOT_CLOSED = "Slot is closed"
SLOT_STARTED = "Slot has already started"
SLOT_TOO_FAR = "Slot is too far ahead"
DOCTOR_NOT_ACTIVE = "Doctor is not active"
SLOT_BOOKED = "Slot is booked"
SLOT_NOT_ENDED = "Slot has not ended"
SLOTS_OVERLAP = "Slots overlap"
ATHLETE_OVERLAP = "Athlete has an overlapping appointment"
TOO_MANY_ACTIVE = "Too many active appointments"
INVALID_APPOINTMENT_STATUS = "Invalid appointment status"
NOT_DUE_TODAY = "Appointment is not due today"
CASE_CHANGED = "Case was changed concurrently, repeat the request"


class SlotTaken(Conflict):
    """The slot already has an active appointment (lost the race, or booked earlier)."""

    default_message = SLOT_TAKEN


class SlotUnavailable(Conflict):
    """The slot cannot be used for this action in its current state (closed, started, too far, doctor inactive...)."""

    default_message = "Slot is unavailable"


class SlotOverlap(Conflict):
    """The new slot intersects an existing slot of the same doctor."""

    default_message = SLOTS_OVERLAP


class AppointmentConflict(Conflict):
    """The appointment (or the athlete's other appointments) does not allow the action."""

    default_message = "Appointment conflict"
