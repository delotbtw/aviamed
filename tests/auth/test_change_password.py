"""Spec section 6, block C: change password."""

import pytest

from app.core.rbac import Role
from tests.helpers import STRONG_PASSWORD, sha256

URL = "/auth/change-password"


async def change(client, user, old, new):
    return await client.post(URL, json={"old_password": old, "new_password": new}, headers=user.headers)


async def can_login(client, email, password) -> int:
    return (await client.post("/auth/login", json={"email": email, "password": password})).status_code


async def test_C1_change_password_switches_credentials(client, doctor):
    resp = await change(client, doctor, doctor.password, STRONG_PASSWORD)

    assert resp.status_code == 204
    assert await can_login(client, doctor.email, doctor.password) == 401
    assert await can_login(client, doctor.email, STRONG_PASSWORD) == 200


async def test_C1_new_hash_is_argon2(client, doctor, sql):
    [before] = await sql("SELECT password_hash FROM users WHERE id = :u", u=doctor.id)

    resp = await change(client, doctor, doctor.password, STRONG_PASSWORD)

    assert resp.status_code == 204
    [row] = await sql("SELECT password_hash FROM users WHERE id = :u", u=doctor.id)
    assert row["password_hash"] != before["password_hash"]
    assert row["password_hash"].startswith("$argon2")


async def test_C2_wrong_old_password_is_400_and_changes_nothing(client, doctor):
    resp = await change(client, doctor, "Wrong-Passw0rd", STRONG_PASSWORD)

    assert resp.status_code == 400
    assert await can_login(client, doctor.email, doctor.password) == 200
    assert await can_login(client, doctor.email, STRONG_PASSWORD) == 401


async def test_C3_new_equal_to_old_is_422(client, doctor):
    assert (await change(client, doctor, doctor.password, doctor.password)).status_code == 422


@pytest.mark.parametrize(
    "new_password",
    ["Ab1", "abcdefghijkl", "1234567890123", "a1" + "x" * 127],
    ids=["too_short", "no_digit", "no_letter", "129_chars"],
)
async def test_C3_policy_violations_are_422(client, doctor, new_password):
    resp = await change(client, doctor, doctor.password, new_password)

    assert resp.status_code == 422
    assert await can_login(client, doctor.email, doctor.password) == 200


async def test_C3_password_equal_to_email_is_422(client, make_user):
    user = await make_user(Role.DOCTOR, email="abcde12345@example.com")

    assert (await change(client, user, user.password, user.email)).status_code == 422


async def test_C3_boundary_lengths_are_accepted(client, make_user):
    ten = "abcdefgh1" + "x"  # exactly 10
    user = await make_user(Role.DOCTOR)
    assert (await change(client, user, user.password, ten)).status_code == 204
    assert (await change(client, user, ten, "a1" + "x" * 126)).status_code == 204  # exactly 128


async def test_C4_all_refresh_tokens_are_revoked(client, doctor, login, sql, redis):
    tokens = [(await login(client, doctor))["refresh_token"] for _ in range(2)]

    await change(client, doctor, doctor.password, STRONG_PASSWORD)

    active = await sql("SELECT id FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL", u=doctor.id)
    assert active == []
    for t in tokens:
        assert len(await redis.keys(f"*{sha256(t)}*")) == 1
        assert (await client.post("/auth/refresh", json={"refresh_token": t})).status_code == 401


async def test_C4_other_users_tokens_are_untouched(client, doctor, registrar, login):
    other = (await login(client, registrar))["refresh_token"]

    await change(client, doctor, doctor.password, STRONG_PASSWORD)

    assert (await client.post("/auth/refresh", json={"refresh_token": other})).status_code == 200


async def test_C5_requires_authentication(client, doctor):
    resp = await client.post(URL, json={"old_password": doctor.password, "new_password": STRONG_PASSWORD})

    assert resp.status_code == 401


async def test_C5_change_is_audited_without_passwords(client, doctor, audit):
    await change(client, doctor, doctor.password, STRONG_PASSWORD)

    rows = await audit("password_change")
    assert [r["user_id"] for r in rows] == [doctor.id]
    dump = str(await audit())
    assert STRONG_PASSWORD not in dump and doctor.password not in dump


async def test_C_wrong_old_password_counts_towards_account_limit(client, doctor):
    for _ in range(5):
        assert (await change(client, doctor, "Wrong-Passw0rd", STRONG_PASSWORD)).status_code == 400

    resp = await client.post("/auth/login", json={"email": doctor.email, "password": doctor.password})

    assert resp.status_code == 429
