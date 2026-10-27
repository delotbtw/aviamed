"""Spec section 6, block G: POST /users/{id}/deactivate."""

import pytest

from app.core.rbac import Role
from tests.helpers import sha256


def url(user_id: int) -> str:
    return f"/users/{user_id}/deactivate"


async def test_G1_admin_deactivates_doctor_without_deleting_row(client, admin, doctor, sql):
    resp = await client.post(url(doctor.id), headers=admin.headers)

    assert resp.status_code == 204
    [row] = await sql("SELECT is_active FROM users WHERE id = :u", u=doctor.id)
    assert row["is_active"] is False


async def test_G2_deactivated_user_loses_all_access_immediately(client, admin, doctor, login, sql, redis):
    pair = await login(client, doctor)
    second = await login(client, doctor)
    await client.post(url(doctor.id), headers=admin.headers)

    assert (
        await client.post("/auth/login", json={"email": doctor.email, "password": doctor.password})
    ).status_code == 401
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {pair['access_token']}"})
    assert me.status_code == 401
    for token in (pair["refresh_token"], second["refresh_token"]):
        assert (await client.post("/auth/refresh", json={"refresh_token": token})).status_code == 401
        assert len(await redis.keys(f"*{sha256(token)}*")) == 1
    active = await sql("SELECT id FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL", u=doctor.id)
    assert active == []


@pytest.mark.parametrize("actor_role", [Role.REGISTRAR, Role.DOCTOR, Role.ATHLETE, Role.COACH])
async def test_G3_non_admin_is_403(client, users_by_role, admin, actor_role, sql):
    resp = await client.post(url(admin.id), headers=users_by_role[actor_role].headers)

    assert resp.status_code == 403
    assert (await sql("SELECT is_active FROM users WHERE id = :u", u=admin.id))[0]["is_active"] is True


async def test_G3_no_token_is_401(client, doctor):
    assert (await client.post(url(doctor.id))).status_code == 401


async def test_G3_unknown_user_is_404(client, admin):
    assert (await client.post(url(999999), headers=admin.headers)).status_code == 404


async def test_G3_admin_cannot_deactivate_self(client, admin, sql):
    resp = await client.post(url(admin.id), headers=admin.headers)

    assert resp.status_code == 409
    assert (await sql("SELECT is_active FROM users WHERE id = :u", u=admin.id))[0]["is_active"] is True


async def test_G4_second_call_is_204_without_second_audit_record(client, admin, doctor, audit):
    first = await client.post(url(doctor.id), headers=admin.headers)
    second = await client.post(url(doctor.id), headers=admin.headers)

    assert first.status_code == 204 and second.status_code == 204
    rows = await audit("user_deactivate")
    assert len(rows) == 1
    assert rows[0]["user_id"] == admin.id and rows[0]["entity_type"] == "user" and rows[0]["entity_id"] == doctor.id
