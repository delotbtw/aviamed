"""Cabinet actions by role: the single source for the side menu."""

from typing import NamedTuple

from app.core.rbac import Action, Role, roles_for
from app.models.user import User


class NavLink(NamedTuple):
    href: str
    label: str
    note: str


SCHEDULE_PATH = "/cabinet/schedule"
APPOINTMENTS_PATH = "/cabinet/appointments"
SLOTS_PATH = "/cabinet/slots"

# Page -> the action that gates it. Pages and the menu both read this, so a link never leads to a 403.
PAGE_ACTIONS: dict[str, Action] = {
    SCHEDULE_PATH: Action.SLOT_VIEW_FREE,
    APPOINTMENTS_PATH: Action.APPOINTMENT_VIEW,
    SLOTS_PATH: Action.SLOT_VIEW,
}

# (action that gates the link or None for everyone, link), shown after the schedule pages.
_LINKS: tuple[tuple[Action | None, NavLink], ...] = (
    (
        Action.ATHLETE_REGISTER,
        NavLink(
            "/cabinet/athletes/new", "Зарегистрировать спортсмена", "Аккаунт, личные данные и номер бумажного согласия"
        ),
    ),
    (
        Action.USER_CREATE,
        NavLink("/cabinet/users/new", "Создать пользователя", "Врач, регистратура, тренер или администратор"),
    ),
)

# The same page reads differently for each role: href -> role -> (label, note). Notes: one sentence, no period.
_SLOTS_MANAGE = ("Слоты врачей", "Слоты любого врача: добавить, закрыть, открыть")
_SCHEDULE_LINKS: dict[str, dict[Role, tuple[str, str]]] = {
    SCHEDULE_PATH: {
        Role.ATHLETE: ("Записаться на приём", "Свободные слоты врачей и запись на удобное время"),
        Role.REGISTRAR: ("Расписание и запись", "Свободные слоты и запись спортсмена на приём"),
        Role.ADMIN: ("Расписание и запись", "Свободные слоты и запись спортсмена на приём"),
        Role.DOCTOR: ("Свободные слоты", "Расписание приёмов всех врачей"),
    },
    APPOINTMENTS_PATH: {
        Role.ATHLETE: ("Моя запись", "Предстоящие приёмы, история и отмена записи"),
        Role.REGISTRAR: ("Очередь и приход", "Записи на день, отметка прихода и неявки"),
        Role.ADMIN: ("Очередь и приход", "Записи на день и отмена записей"),
    },
    SLOTS_PATH: {
        Role.ADMIN: _SLOTS_MANAGE,
        Role.REGISTRAR: _SLOTS_MANAGE,
        Role.DOCTOR: ("Моё расписание", "Ваши слоты и записавшиеся, только просмотр"),
    },
}
_PASSWORD_LINK = NavLink("/cabinet/password", "Сменить пароль", "После смены потребуется войти заново")


def nav_links(user: User | None) -> list[NavLink]:
    """Links the user may open; the sign-in action for guests lives in the template."""
    if user is None:
        return []
    links = [
        NavLink(href, *labels[user.role])
        for href, labels in _SCHEDULE_LINKS.items()
        if user.role in labels and user.role in roles_for(PAGE_ACTIONS[href])
    ]
    links += [link for action, link in _LINKS if action is None or user.role in roles_for(action)]
    return [*links, _PASSWORD_LINK]
