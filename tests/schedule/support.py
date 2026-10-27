"""Plain helpers for the stage 2 tests: time arithmetic (all "now"-relative, Europe/Moscow), API calls, SQL builders.

The fixed "now" is 2026-11-02 09:00 Europe/Moscow (Monday) = 06:00 UTC. Moscow has no DST, so +3 is constant.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from httpx import AsyncClient

from app.core.rbac import Role

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=MSK).astimezone(UTC)
HORIZON_DAYS = 60
GATHER_TIMEOUT_S = 30


def msk(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Moscow wall-clock time -> aware UTC datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=MSK).astimezone(UTC)


def at(hour: int, minute: int = 0, *, days: int = 1) -> datetime:
    """`days` calendar days after "today" (Moscow) at hour:minute Moscow time. Default: tomorrow."""
    today = NOW.astimezone(MSK).date()
    d = today + timedelta(days=days)
    return msk(d.year, d.month, d.day, hour, minute)


def iso(dt: datetime) -> str:
    """JSON form used by tests: UTC with the Z suffix."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, f"naive datetime in a response: {value!r}"
    return parsed


def assert_utc(value: str, expected: datetime) -> None:
    parsed = parse_dt(value)
    assert parsed.utcoffset() == timedelta(0), f"response time must be UTC, got {value!r}"
    assert parsed == expected, (value, expected)


class FakeClock:
    """Injected through the `get_clock` dependency (spec 7.1, contract in section 12)."""

    def __init__(self, now: datetime) -> None:
        assert now.tzinfo is not None
        self._now = now.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        assert now.tzinfo is not None
        self._now = now.astimezone(UTC)

    def advance(self, **kwargs) -> None:
        self._now += timedelta(**kwargs)


async def gather(*coros, timeout: float = GATHER_TIMEOUT_S):
    """Parallel requests with a common timeout: a deadlock fails the test instead of hanging the run."""
    return await asyncio.wait_for(asyncio.gather(*coros), timeout)


# --------------------------------------------------------------------------- API calls


async def post_slot(client: AsyncClient, actor, start: datetime, *, minutes: int = 30, doctor=None, **extra):
    body = {"start_at": iso(start), "end_at": iso(start + timedelta(minutes=minutes)), **extra}
    if doctor is not None:
        body["doctor_id"] = doctor.id
    return await client.post("/schedule/slots", json=body, headers=actor.headers)


async def post_batch(client: AsyncClient, actor, start: datetime, end: datetime, slot_minutes: int, *, doctor=None):
    body = {"start_at": iso(start), "end_at": iso(end), "slot_minutes": slot_minutes}
    if doctor is not None:
        body["doctor_id"] = doctor.id
    return await client.post("/schedule/slots/batch", json=body, headers=actor.headers)


async def book(client: AsyncClient, actor, slot_id: int, athlete=None, **extra):
    """Athletes book themselves (no athlete_id); registrar and admin pass the athlete explicitly."""
    body: dict = {"slot_id": slot_id, **extra}
    if actor.role is not Role.ATHLETE:
        assert athlete is not None, "registrar/admin must name the athlete"
        body["athlete_id"] = athlete.id
    return await client.post("/schedule/appointments", json=body, headers=actor.headers)


async def cancel(client: AsyncClient, actor, appointment_id: int):
    return await client.post(f"/schedule/appointments/{appointment_id}/cancel", headers=actor.headers)


async def arrive(client: AsyncClient, actor, appointment_id: int):
    return await client.post(f"/schedule/appointments/{appointment_id}/arrive", headers=actor.headers)


async def no_show(client: AsyncClient, actor, appointment_id: int):
    return await client.post(f"/schedule/appointments/{appointment_id}/no-show", headers=actor.headers)


async def close_slot(client: AsyncClient, actor, slot_id: int):
    return await client.post(f"/schedule/slots/{slot_id}/close", headers=actor.headers)


async def reopen_slot(client: AsyncClient, actor, slot_id: int):
    return await client.post(f"/schedule/slots/{slot_id}/reopen", headers=actor.headers)


def ids(resp) -> list[int]:
    return [item["id"] for item in resp.json()]


# --------------------------------------------------------------------------- invariants (spec section 11)

_VIOLATIONS: dict[str, str] = {
    "more than one active appointment on a slot": """
        SELECT slot_id AS id FROM appointments WHERE status <> 'cancelled' GROUP BY slot_id HAVING count(*) > 1""",
    "slot.status=booked does not match the existence of an active appointment": """
        SELECT s.id FROM slots s
        WHERE (s.status = 'booked') <> EXISTS (
            SELECT 1 FROM appointments a WHERE a.slot_id = s.id AND a.status <> 'cancelled')""",
    "cancelled_at does not match status=cancelled": """
        SELECT id FROM appointments WHERE (status = 'cancelled') <> (cancelled_at IS NOT NULL)""",
    "appointment without the status_history row of its current status": """
        SELECT a.id FROM appointments a WHERE NOT EXISTS (
            SELECT 1 FROM status_history h
            WHERE h.entity_type = 'appointment' AND h.entity_id = a.id AND h.to_status = a.status::text)""",
    "appointment without the creation row (NULL -> booked)": """
        SELECT a.id FROM appointments a WHERE NOT EXISTS (
            SELECT 1 FROM status_history h
            WHERE h.entity_type = 'appointment' AND h.entity_id = a.id
              AND h.from_status IS NULL AND h.to_status = 'booked')""",
    "slot whose last status_history row disagrees with its status": """
        SELECT s.id FROM slots s
        WHERE EXISTS (SELECT 1 FROM status_history h WHERE h.entity_type = 'slot' AND h.entity_id = s.id)
          AND (SELECT h.to_status FROM status_history h WHERE h.entity_type = 'slot' AND h.entity_id = s.id
               ORDER BY h.id DESC LIMIT 1) <> s.status::text""",
    "slot that changed status without any status_history row": """
        SELECT s.id FROM slots s WHERE s.status <> 'free'
          AND NOT EXISTS (SELECT 1 FROM status_history h WHERE h.entity_type = 'slot' AND h.entity_id = s.id)""",
    "overlapping slots of one doctor": """
        SELECT a.id FROM slots a JOIN slots b
          ON a.doctor_id = b.doctor_id AND a.id < b.id AND a.start_at < b.end_at AND b.start_at < a.end_at""",
}


async def schedule_violations(sql) -> dict[str, list[int]]:
    found = {}
    for name, query in _VIOLATIONS.items():
        rows = await sql(query)
        if rows:
            found[name] = [r["id"] for r in rows]
    return found


async def assert_schedule_invariants(sql) -> None:
    found = await schedule_violations(sql)
    assert found == {}, f"schedule invariants violated: {found}"


# --------------------------------------------------------------------------- pages (HTML helpers)

import re  # noqa: E402

HX = {"HX-Request": "true"}
ORIGIN_EVIL = {"Origin": "https://evil.example"}


def element(html: str, tag: str, element_id: str) -> str:
    """Outer HTML of `<tag ... id="element_id" ...>...</tag>` (first match; no nesting of the same tag assumed)."""
    match = re.search(rf'<{tag}\b[^>]*\bid="{re.escape(element_id)}"[^>]*>.*?</{tag}>', html, re.DOTALL)
    assert match, f"<{tag} id={element_id!r}> not found in:\n{html[:3000]}"
    return match.group(0)


def has_element(html: str, element_id: str) -> bool:
    return re.search(rf'\bid="{re.escape(element_id)}"', html) is not None


def input_tag(html: str, element_id: str) -> str:
    match = re.search(rf'<(?:input|select)\b[^>]*\bid="{re.escape(element_id)}"[^>]*>', html, re.DOTALL)
    assert match, f"field {element_id!r} not found"
    return match.group(0)


def row(html: str, element_id: str) -> str:
    return element(html, "tr", element_id)


def actions(html: str) -> set[str]:
    """Values of data-action attributes inside a fragment (row buttons)."""
    return set(re.findall(r'data-action="([^"]+)"', html))


def is_fragment(html: str) -> bool:
    return "<html" not in html.lower() and "<!doctype" not in html.lower()
