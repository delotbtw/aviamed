"""Russian texts for validation and domain errors shown on pages (API errors stay in English)."""

from pydantic import ValidationError

from app.core.exceptions import (
    AuthenticationFailed,
    BadRequest,
    Conflict,
    DomainError,
    InvalidInput,
    PermissionDenied,
    RateLimited,
)

GENERAL = "_general"

_DOMAIN_TEXTS = {
    "Email is already registered": "Этот email уже зарегистрирован",
    "Consent paper number is already used": "Согласие с таким номером уже оформлено",
    "Unknown sport_id": "Выбран несуществующий вид спорта",
    "Unknown specialty_id": "Выбрана несуществующая специальность",
    "coach_id must point at an active coach": "Выберите активного тренера из списка",
    "Invalid old password": "Неверный текущий пароль",
    "New password must differ from the old one": "Новый пароль должен отличаться от старого",
}
_DOMAIN_FALLBACK: tuple[tuple[type[DomainError], str], ...] = (
    (Conflict, "Такая запись уже существует"),
    (InvalidInput, "Некорректные данные"),
    (BadRequest, "Некорректный запрос"),
    (PermissionDenied, "Недостаточно прав"),
    (AuthenticationFailed, "Требуется вход"),
)
_VALUE_ERROR_PREFIXES = (
    ("Password must be", "Пароль должен содержать от 10 до 128 символов"),
    ("Password must contain", "Пароль должен содержать хотя бы одну букву и одну цифру"),
    ("Password must not be equal", "Пароль не должен совпадать с email"),
    ("Invalid phone", "Неверный формат телефона"),
    ("birth_date must not be in the future", "Дата рождения не может быть в будущем"),
    ("birth_date must not be older", "Дата рождения слишком давняя"),
    ("consent_signed_at", "Дата согласия не может быть в будущем"),
    ("specialty_id is required", "Укажите специальность врача"),
    ("Fields not allowed", "Часть полей не подходит для выбранной роли"),
    ("Athletes are registered", "Спортсменов регистрирует регистратура"),
)
_TYPE_TEXTS = {
    "missing": "Обязательное поле",
    "string_too_short": "Поле не может быть пустым",
    "string_too_long": "Слишком длинное значение",
    "extra_forbidden": "Недопустимое поле",
}


def domain_message(exc: DomainError) -> str:
    text = str(exc)
    if text in _DOMAIN_TEXTS:
        return _DOMAIN_TEXTS[text]
    for kind, fallback in _DOMAIN_FALLBACK:
        if isinstance(exc, kind):
            return fallback
    return "Ошибка выполнения операции"


def rate_limit_message(exc: RateLimited) -> str:
    minutes = max(1, -(-exc.retry_after // 60))
    return f"Слишком много попыток, повторите через {minutes} мин"


def validation_errors(exc: ValidationError) -> dict[str, str]:
    """Field name -> Russian message; errors not tied to a field go under GENERAL."""
    out: dict[str, str] = {}
    for err in exc.errors():
        field = str(err["loc"][0]) if err["loc"] else GENERAL
        text = _TYPE_TEXTS.get(err["type"])
        if text is None and err["type"] == "value_error":
            raw = str(err.get("ctx", {}).get("error", ""))
            text = next((ru for prefix, ru in _VALUE_ERROR_PREFIXES if raw.startswith(prefix)), None)
            if text is None and field == "email":
                text = "Некорректный email"
        out.setdefault(field, text or "Некорректное значение")
    return out
