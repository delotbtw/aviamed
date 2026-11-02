"""Fixes after the security audit and the review of stage 2.1 (S1, S4, S5, S6, R1, R4, R5)."""

import random
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.admin.setup import AdminAuth
from app.core.access_tokens import build_access_tokens
from app.core.config import Settings, get_settings
from app.core.exceptions import PermissionDenied
from app.core.local_time import LocalCalendar
from app.core.rbac import Role
from app.models.user import User
from app.schedule.queries import ScheduleQueryService
from app.schedule.schemas import ManagedSlotsQuery
from app.seed import DemoUsers
from app.seed_schedule import DemoAppointments
from tests.schedule.support import HX, ORIGIN_EVIL, at, row

STRONG_KEY = "k" * 32


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("key", ["change-me", "CHANGE-ME-long-random-string-0123456789", "short-key", "x" * 31])
def test_S1_weak_secret_key_is_rejected_without_debug(key):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        settings(debug=False, secret_key=key)


def test_S1_strong_secret_key_and_debug_are_accepted():
    assert settings(debug=False, secret_key=STRONG_KEY).secret_key == STRONG_KEY
    assert settings(debug=True, secret_key="change-me").debug is True
    assert len(get_settings().secret_key) >= 32  # the key used by the test suite passes the rule


# --------------------------------------------------------------------------- S4


async def test_S4_fragments_are_not_cached(client, registrar, athlete, web_session):
    web_session(client, registrar)

    resp = await client.get("/cabinet/schedule/athletes", params={"q": "Ив"})

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    assert "HX-Request" in resp.headers["Vary"]


# --------------------------------------------------------------------------- S5


def admin_request(token: str) -> Request:
    return Request({"type": "http", "headers": [(b"cookie", f"access_token={token}".encode())], "session": {}})


@pytest.fixture
def admin_auth(session_factory):
    return AdminAuth("s" * 32, build_access_tokens(get_settings()), session_factory)


async def test_S5_active_admin_enters_the_panel(admin_auth, admin):
    assert await admin_auth.authenticate(admin_request(admin.token)) is True


async def test_S5_deactivated_admin_is_refused_with_a_valid_token(admin_auth, admin, sql):
    await sql("UPDATE users SET is_active = false WHERE id = :i", i=admin.id)

    assert await admin_auth.authenticate(admin_request(admin.token)) is False


async def test_S5_demoted_admin_is_refused_with_a_valid_token(admin_auth, admin, sql):
    await sql("UPDATE users SET role = 'registrar' WHERE id = :i", i=admin.id)

    assert await admin_auth.authenticate(admin_request(admin.token)) is False


async def test_S5_non_admin_and_missing_token_are_refused(admin_auth, registrar):
    assert await admin_auth.authenticate(admin_request(registrar.token)) is False
    assert await admin_auth.authenticate(admin_request("")) is False


# --------------------------------------------------------------------------- S6


async def test_S6_only_a_bearer_header_skips_the_origin_check(client, clock, admin, web_session):
    web_session(client, admin)
    url = "/cabinet/slots/1/close"

    basic = await client.post(url, headers={**ORIGIN_EVIL, "Authorization": "Basic Zm9vOmJhcg=="})
    bearer = await client.post(url, headers={**ORIGIN_EVIL, "Authorization": "Bearer not-a-token"})

    assert basic.status_code == 403
    assert bearer.status_code != 403


# --------------------------------------------------------------------------- R1


@pytest.mark.parametrize("role", [Role.ADMIN, Role.REGISTRAR])
async def test_R1_row_after_close_keeps_the_doctor_cell_for_admin_and_registrar(
    client, clock, users_by_role, doctor, make_slot, web_session, role
):
    slot_id = await make_slot(doctor, at(10))
    web_session(client, users_by_role[role])

    resp = await client.post(f"/cabinet/slots/{slot_id}/close", headers=HX)
    page = await client.get(
        "/cabinet/slots", params={"date": LocalCalendar("Europe/Moscow").day_of(at(10)).strftime("%d.%m.%Y")}
    )

    after = row(resp.text, f"slot-{slot_id}")
    assert 'data-label="Врач"' in after and "Иванов" in after
    assert after.count("<td") == row(page.text, f"slot-{slot_id}").count("<td") == 5


# --------------------------------------------------------------------------- R4


@pytest.mark.parametrize("role", [Role.ATHLETE, Role.COACH])
async def test_R4_managed_slots_are_refused_to_roles_without_slot_view(role):
    service = ScheduleQueryService(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    actor = User(id=1, role=role)

    with pytest.raises(PermissionDenied):
        await service.managed_slots(ManagedSlotsQuery(), actor)
    with pytest.raises(PermissionDenied):
        await service.managed_slot(1, actor)


# --------------------------------------------------------------------------- R5


async def test_R5_consent_date_follows_the_moscow_calendar():
    clock = MagicMock()
    clock.now.return_value = datetime(2026, 10, 31, 22, 30, tzinfo=UTC)  # already 1 November in Moscow
    consents = MagicMock(add=AsyncMock())
    users = DemoUsers(
        MagicMock(create=AsyncMock(return_value=User(id=5))),
        MagicMock(get_by_email=AsyncMock(return_value=None)),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(add=AsyncMock()),
        consents,
        clock,
        LocalCalendar("Europe/Moscow"),
    )

    await users._athlete(MagicMock(), 0, coach_id=1, sport_id=1)

    assert consents.add.call_args.args[0].signed_at == date(2026, 11, 1)


def test_R5_pick_reports_a_lack_of_slots_clearly():
    with pytest.raises(RuntimeError, match="free slots"):
        DemoAppointments._pick(random.Random(1), [], 3)
