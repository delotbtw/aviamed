"""The only source of "now" for the schedule: services, routers and pages take it from here, tests replace it."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Aware UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def get_clock() -> Clock:
    """FastAPI dependency; tests override it through `app.dependency_overrides`."""
    return SystemClock()
