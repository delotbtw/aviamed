"""Spec section 6, block R: the permission matrix (docs/03) on every /schedule endpoint, per role."""

from pathlib import Path

import pytest
import pytest_asyncio

from app.core.rbac import Action, Role, Scope, roles_for, scope_for
from tests.schedule.support import iso, msk

ADMIN, REGISTRAR, DOCTOR, ATHLETE, COACH = Role.ADMIN, Role.REGISTRAR, Role.DOCTOR, Role.ATHLETE, Role.COACH
ALL_ROLES = [ADMIN, REGISTRAR, DOCTOR, ATHLETE, COACH]

ALLOWED: dict[str, set[Role]] = {
    "free_slots": {ADMIN, REGISTRAR, DOCTOR, ATHLETE},
    "manage_slots": {ADMIN, DOCTOR},
    "create_slot": {ADMIN, DOCTOR},
    "create_batch": {ADMIN, DOCTOR},
    "close_slot": {ADMIN, DOCTOR},
    "reopen_slot": {ADMIN, DOCTOR},
    "book": {ADMIN, REGISTRAR, ATHLETE},
    "list_appointments": {ADMIN, REGISTRAR, ATHLETE},
    "cancel": {ADMIN, REGISTRAR, ATHLETE},
    "arrive": {REGISTRAR},
    "no_show": {REGISTRAR},
}


@pytest_asyncio.fixture
async def world(client, clock, athlete, doctor, make_slot, insert_booking):
    """One booked appointment for today (so that arrive/no-show/cancel have a target), free and closed slots."""
    booked_slot = await make_slot(doctor, msk(2026, 11, 2, 12))
    return {
        "appointment_id": await insert_booking(booked_slot, athlete),
        "free_slot": await make_slot(doctor, msk(2026, 11, 3, 10)),
        "closed_slot": await make_slot(doctor, msk(2026, 11, 3, 12), status="closed"),
        "doctor": doctor,
        "athlete": athlete,
    }


def build_request(endpoint: str, actor, w: dict) -> tuple[str, str, dict]:
    start, end = msk(2026, 11, 4, 10), msk(2026, 11, 4, 10, 30)
    doctor_part = {"doctor_id": w["doctor"].id} if actor.role is ADMIN else {}
    athlete_part = {} if actor.role is ATHLETE else {"athlete_id": w["athlete"].id}
    aid, free, closed = w["appointment_id"], w["free_slot"], w["closed_slot"]
    return {
        "free_slots": ("GET", "/schedule/slots", {}),
        "manage_slots": ("GET", "/schedule/slots/all", {}),
        "create_slot": (
            "POST",
            "/schedule/slots",
            {"json": {"start_at": iso(start), "end_at": iso(end), **doctor_part}},
        ),
        "create_batch": (
            "POST",
            "/schedule/slots/batch",
            {"json": {"start_at": iso(start), "end_at": iso(end), "slot_minutes": 10, **doctor_part}},
        ),
        "close_slot": ("POST", f"/schedule/slots/{free}/close", {}),
        "reopen_slot": ("POST", f"/schedule/slots/{closed}/reopen", {}),
        "book": ("POST", "/schedule/appointments", {"json": {"slot_id": free, **athlete_part}}),
        "list_appointments": ("GET", "/schedule/appointments", {}),
        "cancel": ("POST", f"/schedule/appointments/{aid}/cancel", {}),
        "arrive": ("POST", f"/schedule/appointments/{aid}/arrive", {}),
        "no_show": ("POST", f"/schedule/appointments/{aid}/no-show", {}),
    }[endpoint]


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.parametrize("endpoint", list(ALLOWED))
async def test_R_matrix(client, users_by_role, world, endpoint, role):
    actor = users_by_role[role]
    method, url, kwargs = build_request(endpoint, actor, world)

    resp = await client.request(method, url, headers=actor.headers, **kwargs)

    if role in ALLOWED[endpoint]:
        assert resp.status_code not in (401, 403) and resp.status_code < 500, (resp.status_code, resp.text)
    else:
        assert resp.status_code == 403, (resp.status_code, resp.text)


@pytest.mark.parametrize("endpoint", list(ALLOWED))
async def test_R_every_endpoint_requires_a_token(client, world, users_by_role, endpoint):
    method, url, kwargs = build_request(endpoint, users_by_role[ADMIN], world)

    resp = await client.request(method, url, **kwargs)

    assert resp.status_code == 401


@pytest.mark.parametrize("endpoint", list(ALLOWED))
async def test_R6_deactivated_user_is_401_everywhere_and_keeps_the_data(client, users_by_role, world, sql, endpoint):
    role = sorted(ALLOWED[endpoint], key=lambda r: r.value)[0]
    actor = users_by_role[role]
    method, url, kwargs = build_request(endpoint, actor, world)
    appointments_before = await sql("SELECT id, status FROM appointments ORDER BY id")
    await sql("UPDATE users SET is_active = false WHERE id = :i", i=actor.id)

    resp = await client.request(method, url, headers=actor.headers, **kwargs)

    assert resp.status_code == 401
    assert await sql("SELECT id, status FROM appointments ORDER BY id") == appointments_before


async def test_R6_deactivated_athlete_keeps_his_appointments_in_the_database(
    client, clock, athlete, doctor, make_slot, make_booking, sql
):
    appointment_id = await make_booking(await make_slot(doctor, msk(2026, 11, 3, 10)), athlete)
    await sql("UPDATE users SET is_active = false WHERE id = :i", i=athlete.id)

    assert (await client.get("/schedule/appointments", headers=athlete.headers)).status_code == 401
    assert [r["id"] for r in await sql("SELECT id FROM appointments")] == [appointment_id]


def test_R_appointment_view_action_matches_the_matrix():
    assert roles_for(Action.APPOINTMENT_VIEW) == {ADMIN, REGISTRAR, ATHLETE}
    assert scope_for(Action.APPOINTMENT_VIEW, ADMIN) is Scope.FULL
    assert scope_for(Action.APPOINTMENT_VIEW, REGISTRAR) is Scope.FULL
    assert scope_for(Action.APPOINTMENT_VIEW, ATHLETE) is Scope.OWN
    assert scope_for(Action.APPOINTMENT_VIEW, DOCTOR) is None


def test_R_matrix_document_has_the_appointment_view_row():
    matrix = (Path(__file__).resolve().parents[2] / "docs" / "03_matrix.md").read_text()
    row = next(line for line in matrix.splitlines() if line.startswith("| Видеть записи"))
    cells = [c.strip() for c in row.strip("|").split("|")][1:]
    admin, registrar, doctor, athlete, coach = (
        cells  # column order of docs/03 section 3: admin, registrar, doctor, athlete, coach
    )
    assert admin.startswith("✓") and registrar.startswith("✓") and athlete == "свои" and coach == "—"
    assert "ФИО" in doctor
