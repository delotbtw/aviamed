"""Single entry point for status changes (docs/05 section 2): `StatusChanger`.

Checks the transition and the actor, updates the entity and writes status_history
in the caller's transaction. The caller should load the entity with get_for_update().
"""

from enum import StrEnum
from typing import Literal, Protocol

from app.core.rbac import Role
from app.models.enums import AppointmentStatus, CaseStatus, ExamStatus, SlotStatus
from app.models.system import StatusHistory
from app.repositories.system import StatusHistoryRepository

Actor = Role | Literal["system"]
SYSTEM: Literal["system"] = "system"

type Transitions[S] = dict[tuple[S, S], frozenset[Actor]]

CASE_TRANSITIONS: Transitions[CaseStatus] = {
    (CaseStatus.REGISTERED, CaseStatus.IN_PROGRESS): frozenset({Role.REGISTRAR}),
    (CaseStatus.IN_PROGRESS, CaseStatus.AWAITING_CONCLUSION): frozenset({SYSTEM}),
    (CaseStatus.AWAITING_CONCLUSION, CaseStatus.COMPLETED): frozenset({Role.DOCTOR}),  # + can_issue_conclusion
    (CaseStatus.REGISTERED, CaseStatus.CANCELLED): frozenset({Role.REGISTRAR, Role.ADMIN}),
    (CaseStatus.IN_PROGRESS, CaseStatus.CANCELLED): frozenset({Role.REGISTRAR, Role.ADMIN}),
    (CaseStatus.COMPLETED, CaseStatus.EXPIRED): frozenset({SYSTEM}),
}

APPOINTMENT_TRANSITIONS: Transitions[AppointmentStatus] = {
    (AppointmentStatus.BOOKED, AppointmentStatus.ARRIVED): frozenset({Role.REGISTRAR}),
    (AppointmentStatus.ARRIVED, AppointmentStatus.DONE): frozenset({Role.DOCTOR}),
    (AppointmentStatus.BOOKED, AppointmentStatus.CANCELLED): frozenset({Role.ATHLETE, Role.REGISTRAR, Role.ADMIN}),
    (AppointmentStatus.BOOKED, AppointmentStatus.NO_SHOW): frozenset({Role.REGISTRAR, SYSTEM}),
}

_ATHLETE_STAFF = frozenset({Role.ATHLETE, Role.REGISTRAR, Role.ADMIN})
_SLOT_MANAGERS = frozenset({Role.REGISTRAR, Role.ADMIN})

SLOT_TRANSITIONS: Transitions[SlotStatus] = {
    (SlotStatus.FREE, SlotStatus.BOOKED): _ATHLETE_STAFF,
    (SlotStatus.BOOKED, SlotStatus.FREE): _ATHLETE_STAFF,
    (SlotStatus.FREE, SlotStatus.CLOSED): _SLOT_MANAGERS,
    (SlotStatus.CLOSED, SlotStatus.FREE): _SLOT_MANAGERS,
}

EXAM_TRANSITIONS: Transitions[ExamStatus] = {
    (ExamStatus.PENDING, ExamStatus.DONE): frozenset({Role.DOCTOR}),
}


class InvalidTransition(Exception):
    pass


class _HasStatus(Protocol):
    id: int
    status: StrEnum


class StatusChanger:
    """Checks the transition and the actor, updates the entity and writes status_history in the caller's transaction."""

    def __init__(self, history: StatusHistoryRepository) -> None:
        self.history = history

    async def change(
        self,
        entity: _HasStatus,
        *,
        entity_type: str,
        to_status: StrEnum,
        transitions: Transitions,
        actor: Actor,
        actor_id: int | None = None,
        comment: str | None = None,
    ) -> None:
        key = (entity.status, to_status)
        allowed = transitions.get(key)
        if allowed is None:
            raise InvalidTransition(f"{entity.status} -> {to_status} is not allowed")
        if actor not in allowed:
            raise InvalidTransition(f"{actor} cannot do {entity.status} -> {to_status}")
        from_status = str(entity.status)
        entity.status = to_status
        await self.history.add(
            StatusHistory(
                entity_type=entity_type,
                entity_id=entity.id,
                from_status=from_status,
                to_status=str(to_status),
                changed_by=actor_id,
                comment=comment,
            )
        )  # the flush also writes the entity

    async def created(self, *, entity_type: str, entity_id: int, status: StrEnum, actor_id: int | None) -> None:
        """First history row of an entity (NULL -> status): there is no "from" state to check."""
        await self.history.add(
            StatusHistory(
                entity_type=entity_type,
                entity_id=entity_id,
                from_status=None,
                to_status=str(status),
                changed_by=actor_id,
            )
        )
