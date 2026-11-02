"""Russian texts for the schedule pages: what a domain error means in the context of the action that failed.

The same `Slot has already started` reads differently when booking, cancelling or reopening, so every action has its
own table (detail of the domain error -> text). Anything not listed falls back to the generic texts.
"""

from collections.abc import Mapping

from app.core.config import Settings
from app.core.exceptions import DomainError, InvalidInput, LockTimeout, PermissionDenied
from app.schedule import exceptions as codes
from app.schedule import planning
from app.web import messages

NOT_A_NUMBER = "Выберите значение из списка"
CHOOSE_ATHLETE = "Выберите спортсмена"
CHOOSE_DOCTOR = "Выберите врача"
CHOOSE_SLOT = "Выберите слот"
DATES_REVERSED = "Начальная дата позже конечной"
OVERLAP = "Слот пересекается с уже существующим"
BUSY = "Запись занята другим действием, повторите через секунду"
NO_RIGHTS = "Недостаточно прав"

BOOKING: Mapping[str, str] = {
    codes.SLOT_TAKEN: "Слот уже занят, выберите другой",
    codes.SLOT_CLOSED: "Слот закрыт для записи",
    codes.SLOT_STARTED: "Приём уже начался, запись невозможна",
    codes.SLOT_TOO_FAR: "Запись на эту дату пока недоступна",
    codes.DOCTOR_NOT_ACTIVE: "Врач не принимает, выберите другого",
    codes.ATHLETE_OVERLAP: "У спортсмена уже есть запись на это время",
    codes.TOO_MANY_ACTIVE: "Достигнут лимит активных записей",
    "Slot not found": "Слот не найден",
    "athlete_id must point at an active athlete": "Выберите активного спортсмена из списка",
}
APPOINTMENT_NOT_FOUND = "Запись не найдена"
_APPOINTMENT: Mapping[str, str] = {
    codes.INVALID_APPOINTMENT_STATUS: "Действие недоступно для текущего статуса записи",
    "Appointment not found": APPOINTMENT_NOT_FOUND,
}
CANCEL: Mapping[str, str] = {**_APPOINTMENT, codes.SLOT_STARTED: "Приём уже начался, отмена невозможна"}
ARRIVE: Mapping[str, str] = {
    **_APPOINTMENT,
    codes.NOT_DUE_TODAY: "Приход можно отметить только в день приёма",
    codes.CASE_CHANGED: "Данные дела изменились, повторите отметку",
}
NO_SHOW: Mapping[str, str] = {**_APPOINTMENT, codes.SLOT_NOT_ENDED: "Приём ещё не закончился"}
SLOT_ACTION: Mapping[str, str] = {
    codes.SLOT_BOOKED: "Слот занят, сначала отмените запись",
    codes.SLOT_STARTED: "Приём уже начался, слот нельзя открыть",
    "Slot not found": "Слот не найден",
}
SLOT_CREATE: Mapping[str, str] = {codes.SLOTS_OVERLAP: OVERLAP}


def action_message(exc: DomainError, texts: Mapping[str, str]) -> str:
    """Text of the failed action; the detail of the domain error picks the row, `Slots overlap: <time>` included."""
    detail = str(exc)
    if detail in texts:
        return texts[detail]
    if detail.startswith(codes.SLOTS_OVERLAP) and codes.SLOTS_OVERLAP in texts:
        return texts[codes.SLOTS_OVERLAP]
    if isinstance(exc, LockTimeout):
        return BUSY
    if isinstance(exc, PermissionDenied):
        return NO_RIGHTS
    return messages.domain_message(exc)


def slot_form_error(exc: InvalidInput, settings: Settings, *, batch: bool) -> tuple[str, str]:
    """(field, text) for a rule of the slot planner or the doctor check that the form could not catch itself."""
    detail = str(exc)
    low, high = settings.slot_min_minutes, settings.slot_max_minutes
    length_field = "slot_minutes" if batch else "end_time"
    table: dict[str, tuple[str, str]] = {
        planning.SLOT_IN_PAST: ("start_time", "Время начала должно быть в будущем"),
        planning.END_NOT_AFTER_START: ("end_time", "Окончание должно быть позже начала"),
        planning.BEYOND_HORIZON: (
            "slot_date",
            f"Расписание ведётся не дальше чем на {settings.schedule_horizon_days} дн.",
        ),
        planning.WINDOW_TOO_LONG: ("end_time", "Смена не может быть длиннее 12 часов"),
        planning.WINDOW_NOT_DIVISIBLE: ("slot_minutes", "Смена должна делиться на слоты нацело"),
        "doctor_id must point at an active doctor": ("slot_doctor_id", "Выберите активного врача из списка"),
    }
    if detail in table:
        return table[detail]
    if detail.startswith("Slot length must be"):
        return length_field, f"Длина слота должна быть от {low} до {high} минут"
    if detail.startswith("Too many slots"):
        return "slot_minutes", f"В смене не может быть больше {settings.batch_max_slots} слотов"
    return messages.GENERAL, messages.domain_message(exc)
