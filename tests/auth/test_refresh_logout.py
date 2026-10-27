"""Spec section 6, block B: refresh rotation and logout."""

import jwt
import pytest

from app.core.config import get_settings
from app.core.rbac import Role
from tests.helpers import GENERIC_REFRESH_ERROR, sha256

REFRESH = "/auth/refresh"
LOGOUT = "/auth/logout"
WEEK = 7 * 24 * 3600


async def refresh(client, token):
    return await client.post(REFRESH, json={"refresh_token": token})


async def test_B1_refresh_rotates_token_and_blacklists_old_one(client, doctor, login, sql, redis):
    old = (await login(client, doctor))["refresh_token"]

    resp = await refresh(client, old)

    assert resp.status_code == 200
    new = resp.json()
    assert new["access_token"] and new["refresh_token"] and new["refresh_token"] != old

    [old_row] = await sql("SELECT * FROM refresh_tokens WHERE token_hash = :h", h=sha256(old))
    assert old_row["revoked_at"] is not None
    [new_row] = await sql("SELECT * FROM refresh_tokens WHERE token_hash = :h", h=sha256(new["refresh_token"]))
    assert new_row["revoked_at"] is None and new_row["user_id"] == doctor.id

    keys = await redis.keys(f"*{sha256(old)}*")
    assert len(keys) == 1
    assert 0 < await redis.ttl(keys[0]) <= WEEK


async def test_B1_new_access_token_works(client, doctor, login):
    old = (await login(client, doctor))["refresh_token"]
    new = (await refresh(client, old)).json()

    resp = await client.get("/users/me", headers={"Authorization": f"Bearer {new['access_token']}"})

    assert resp.status_code == 200 and resp.json()["id"] == doctor.id


async def test_B1_new_token_keeps_user_agent(client, doctor, login, sql):
    old = (await login(client, doctor, user_agent="agent-X/9"))["refresh_token"]
    new = (await client.post(REFRESH, json={"refresh_token": old}, headers={"User-Agent": "agent-X/9"})).json()

    [row] = await sql("SELECT user_agent FROM refresh_tokens WHERE token_hash = :h", h=sha256(new["refresh_token"]))
    assert row["user_agent"] == "agent-X/9"


async def test_B2_reuse_of_rotated_token_revokes_everything(client, doctor, login, sql, audit):
    first = (await login(client, doctor))["refresh_token"]
    second = (await login(client, doctor))["refresh_token"]  # another active session
    rotated = (await refresh(client, first)).json()["refresh_token"]

    resp = await refresh(client, first)  # replay

    assert resp.status_code == 401
    active = await sql("SELECT id FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL", u=doctor.id)
    assert active == []
    assert (await refresh(client, rotated)).status_code == 401
    assert (await refresh(client, second)).status_code == 401
    rows = await audit("token_reuse_detected")
    assert [r["user_id"] for r in rows] == [doctor.id]


async def test_B2_successful_refresh_is_audited(client, doctor, login, audit):
    await refresh(client, (await login(client, doctor))["refresh_token"])

    assert [r["user_id"] for r in await audit("token_refresh")] == [doctor.id]


async def test_B3_unknown_expired_and_revoked_tokens_give_same_401(client, doctor, login, sql):
    expired = (await login(client, doctor))["refresh_token"]
    await sql(
        "UPDATE refresh_tokens SET expires_at = now() - interval '1 minute' WHERE token_hash = :h", h=sha256(expired)
    )
    revoked = (await login(client, doctor))["refresh_token"]
    await sql("UPDATE refresh_tokens SET revoked_at = now() WHERE token_hash = :h", h=sha256(revoked))

    responses = [await refresh(client, t) for t in ("totally-unknown-token", expired, revoked)]

    assert [r.status_code for r in responses] == [401, 401, 401]
    assert {r.json()["detail"] for r in responses} == {GENERIC_REFRESH_ERROR}


async def test_B4_refresh_of_deactivated_user_is_401(client, doctor, login, sql):
    token = (await login(client, doctor))["refresh_token"]
    await sql("UPDATE users SET is_active = false WHERE id = :u", u=doctor.id)

    resp = await refresh(client, token)

    assert resp.status_code == 401
    assert resp.json()["detail"] == GENERIC_REFRESH_ERROR


async def test_B5_refresh_uses_db_when_redis_is_down(client, doctor, login, sql, redis_down):
    good = (await login(client, doctor))["refresh_token"]
    revoked = (await login(client, doctor))["refresh_token"]
    await sql("UPDATE refresh_tokens SET revoked_at = now() WHERE token_hash = :h", h=sha256(revoked))
    redis_down()

    assert (await refresh(client, good)).status_code == 200
    assert (await refresh(client, revoked)).status_code == 401


async def test_B6_new_access_token_carries_current_role_from_db(client, doctor, login, sql):
    token = (await login(client, doctor))["refresh_token"]
    await sql("UPDATE users SET role = 'registrar' WHERE id = :u", u=doctor.id)

    new = (await refresh(client, token)).json()

    s = get_settings()
    claims = jwt.decode(new["access_token"], s.secret_key, algorithms=[s.jwt_algorithm])
    assert claims["role"] == Role.REGISTRAR.value
    assert claims["type"] == "access" and claims["sub"] == str(doctor.id)


async def test_B7_logout_revokes_token_and_blacklists_it(client, doctor, login, sql, redis, audit):
    token = (await login(client, doctor))["refresh_token"]

    resp = await client.post(LOGOUT, json={"refresh_token": token})

    assert resp.status_code == 204
    [row] = await sql("SELECT revoked_at FROM refresh_tokens WHERE token_hash = :h", h=sha256(token))
    assert row["revoked_at"] is not None
    keys = await redis.keys(f"*{sha256(token)}*")
    assert len(keys) == 1 and await redis.ttl(keys[0]) > 0
    assert (await refresh(client, token)).status_code == 401
    assert [r["user_id"] for r in await audit("logout")] == [doctor.id]


async def test_B7_logout_does_not_touch_other_sessions(client, doctor, login):
    one = (await login(client, doctor))["refresh_token"]
    two = (await login(client, doctor))["refresh_token"]

    await client.post(LOGOUT, json={"refresh_token": one})

    assert (await refresh(client, two)).status_code == 200


async def test_B8_logout_is_idempotent_and_silent(client, doctor, login, audit):
    token = (await login(client, doctor))["refresh_token"]
    await client.post(LOGOUT, json={"refresh_token": token})
    before = len(await audit())

    unknown = await client.post(LOGOUT, json={"refresh_token": "never-issued"})
    again = await client.post(LOGOUT, json={"refresh_token": token})

    assert unknown.status_code == 204 and again.status_code == 204
    assert len(await audit()) == before


async def test_B9_access_token_is_not_accepted_as_refresh(client, doctor, login):
    pair = await login(client, doctor)

    assert (await refresh(client, pair["access_token"])).status_code == 401


async def test_B9_refresh_token_is_not_accepted_as_bearer(client, doctor, login):
    pair = await login(client, doctor)

    resp = await client.get("/users/me", headers={"Authorization": f"Bearer {pair['refresh_token']}"})

    assert resp.status_code == 401


@pytest.mark.parametrize("url", [REFRESH, LOGOUT])
async def test_refresh_and_logout_validate_body_422(client, url):
    assert (await client.post(url, json={})).status_code == 422
