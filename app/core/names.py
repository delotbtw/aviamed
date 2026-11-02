def full_name(last_name: str, first_name: str, middle_name: str | None) -> str:
    """ "Фамилия Имя Отчество"; the patronymic is omitted when there is none."""
    return " ".join(part for part in (last_name, first_name, middle_name) if part)
