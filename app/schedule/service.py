"""Public entry point of the schedule services.

The services live in their own modules (slots, booking, attendance, queries); the domain errors are part of the
contract (spec 12.1) and are imported from here.
"""

from app.schedule.attendance import AttendanceService
from app.schedule.booking import BookingService
from app.schedule.exceptions import AppointmentConflict, SlotOverlap, SlotTaken, SlotUnavailable
from app.schedule.queries import ScheduleDirectory, ScheduleQueryService
from app.schedule.slots import SlotService

__all__ = [
    "AppointmentConflict",
    "AttendanceService",
    "BookingService",
    "ScheduleDirectory",
    "ScheduleQueryService",
    "SlotOverlap",
    "SlotService",
    "SlotTaken",
    "SlotUnavailable",
]
