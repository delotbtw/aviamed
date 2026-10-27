"""Cabinet actions by role: the single source for the top bar and the cabinet start page."""

from typing import NamedTuple

from app.core.rbac import Action, roles_for
from app.models.user import User


class NavLink(NamedTuple):
    href: str
    label: str
    note: str


# (action that gates the link or None for everyone, link). Order is the display order.
_LINKS: tuple[tuple[Action | None, NavLink], ...] = (
    (
        Action.ATHLETE_REGISTER,
        NavLink(
            "/cabinet/athletes/new", "Зарегистрировать спортсмена", "Аккаунт, личные данные и номер бумажного согласия."
        ),
    ),
    (
        Action.USER_CREATE,
        NavLink("/cabinet/users/new", "Создать пользователя", "Врач, регистратура, тренер или администратор."),
    ),
    (None, NavLink("/cabinet/password", "Сменить пароль", "После смены потребуется войти заново.")),
)


def nav_links(user: User | None) -> list[NavLink]:
    """Links the user may open; the sign-in action for guests lives in the template."""
    if user is None:
        return []
    return [link for action, link in _LINKS if action is None or user.role in roles_for(action)]
