"""Who may act on whose behalf in the schedule. Pure rules on the actor and the request, no I/O."""

from app.core.exceptions import InvalidInput, PermissionDenied
from app.core.rbac import Action, Role, Scope, roles_for, scope_for
from app.models.user import User


def can_manage_slots(actor: User) -> bool:
    """The one meaning of "may manage slots": the right Action.SLOT_CREATE (admin and registrar)."""
    return actor.role in roles_for(Action.SLOT_CREATE)


def sees_all_doctors(actor: User) -> bool:
    """Full scope of Action.SLOT_VIEW: slots of every doctor (a doctor sees his own only)."""
    return scope_for(Action.SLOT_VIEW, actor.role) is Scope.FULL


def require_slot_viewer(actor: User) -> None:
    if actor.role not in roles_for(Action.SLOT_VIEW):
        raise PermissionDenied("The slot table is not available for this role")


def require_slot_manager(actor: User) -> None:
    """Slots are created, closed and reopened by admin and registrar only (Action.SLOT_CREATE)."""
    if not can_manage_slots(actor):
        raise PermissionDenied("Slots are managed by admin and registrar only")


def slot_owner_id(actor: User, requested: int | None) -> int:
    """Admin and registrar name the doctor; anyone else is refused."""
    require_slot_manager(actor)
    if requested is None:
        raise InvalidInput("doctor_id is required")
    return requested


def appointment_athlete_id(actor: User, requested: int | None) -> int:
    """Athlete: only himself. Registrar and admin: name the athlete."""
    if actor.role is Role.ATHLETE:
        if requested not in (None, actor.id):
            raise PermissionDenied("Athletes book only for themselves")
        return actor.id
    if requested is None:
        raise InvalidInput("athlete_id is required")
    return requested
