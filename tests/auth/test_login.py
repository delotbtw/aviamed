"""Spec section 6, block A: login and rate limit."""

import pytest

from app.core.rbac import Role
from tests.helpers import GENERIC_LOGIN_ERROR, sha256

URL = "/auth/login"


async def bad_login(client, email, password="Wrong-Passw0rd"):
    return await client.post(URL, json={"email": email, "password": password})


async def test_A1_login_success_stores_hashed_refresh_token(client, doctor, sql):
    resp = await client.post(
        URL, json={"email": doctor.email, "password": doctor.password}, headers={"User-Agent": "pytest-agent/1.0"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"

    rows = await sql("SELECT * FROM refresh_tokens WHERE user_id = :u", u=doctor.id)
    assert len(rows) == 1
    assert rows[0]["token_hash"] == sha256(body["refresh_token"])
    assert rows[0]["token_hash"] != body["refresh_token"]
    assert rows[0]["user_agent"] == "pytest-agent/1.0"
    assert rows[0]["revoked_at"] is None
    [user] = await sql("SELECT last_login_at FROM users WHERE id = :u", u=doctor.id)
    assert user["last_login_at"] is not None


async def test_A2_all_login_failures_are_indistinguishable(client, doctor, make_user):
    inactive = await make_user(Role.REGISTRAR, is_active=False)

    responses = [
        await bad_login(client, doctor.email),  # wrong password
        await bad_login(client, "nobody1@example.com"),  # no such user
        await client.post(URL, json={"email": inactive.email, "password": inactive.password}),  # inactive
    ]

    assert [r.status_code for r in responses] == [401, 401, 401]
    details = {r.json()["detail"] for r in responses}
    assert details == {GENERIC_LOGIN_ERROR}


async def test_A2_email_is_trimmed_and_case_insensitive(client, doctor):
    resp = await client.post(URL, json={"email": f"  {doctor.email.upper()} ", "password": doctor.password})
    assert resp.status_code == 200


async def test_A3_sixth_attempt_is_blocked_even_with_correct_password(client, doctor):
    for _ in range(5):
        assert (await bad_login(client, doctor.email)).status_code == 401

    resp = await client.post(URL, json={"email": doctor.email, "password": doctor.password})

    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


async def test_A4_login_works_again_after_window_expires(client, doctor, redis):
    for _ in range(5):
        await bad_login(client, doctor.email)
    assert (await client.post(URL, json={"email": doctor.email, "password": doctor.password})).status_code == 429

    await redis.flushall()  # every counter key expires with the window

    resp = await client.post(URL, json={"email": doctor.email, "password": doctor.password})
    assert resp.status_code == 200


async def test_A4_counter_keys_have_ttl_of_the_window(client, doctor, redis):
    await bad_login(client, doctor.email)

    keys = await redis.keys("*")
    assert keys, "failed login must leave a counter in Redis"
    for key in keys:
        assert 0 < await redis.ttl(key) <= 900


async def test_A5_successful_login_resets_account_counter(client, doctor):
    for _ in range(4):
        await bad_login(client, doctor.email)
    assert (await client.post(URL, json={"email": doctor.email, "password": doctor.password})).status_code == 200
    for _ in range(4):
        assert (await bad_login(client, doctor.email)).status_code == 401

    resp = await client.post(URL, json={"email": doctor.email, "password": doctor.password})
    assert resp.status_code == 200

    # the counter really restarted from zero after the success: exactly 5 fresh failures block again
    for _ in range(5):
        await bad_login(client, doctor.email)
    blocked = await client.post(URL, json={"email": doctor.email, "password": doctor.password})
    assert blocked.status_code == 429


async def test_A6_ip_limit_applies_across_different_emails(client, doctor):
    for i in range(20):
        assert (await bad_login(client, f"ghost{i}@example.com")).status_code == 401

    resp = await client.post(URL, json={"email": doctor.email, "password": doctor.password})

    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


async def test_A6_successful_login_does_not_reset_ip_counter(client, doctor):
    for i in range(19):
        await bad_login(client, f"ghost{i}@example.com")
    assert (await client.post(URL, json={"email": doctor.email, "password": doctor.password})).status_code == 200
    assert (await bad_login(client, "ghost-last@example.com")).status_code == 401  # 20th failure

    resp = await client.post(URL, json={"email": doctor.email, "password": doctor.password})

    assert resp.status_code == 429


async def test_A7_limit_applies_to_nonexistent_email_like_to_existing(client):
    email = "ghost-account@example.com"
    for _ in range(5):
        assert (await bad_login(client, email)).status_code == 401

    resp = await bad_login(client, email)

    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


async def test_A7_email_case_does_not_bypass_limit(client, doctor):
    for _ in range(5):
        await bad_login(client, doctor.email)

    resp = await client.post(URL, json={"email": doctor.email.upper(), "password": doctor.password})

    assert resp.status_code == 429


async def test_A8_login_works_when_redis_is_down(client, doctor, redis_down):
    redis_down()

    resp = await client.post(URL, json={"email": doctor.email, "password": doctor.password})

    assert resp.status_code == 200


async def test_A8_failed_login_is_401_not_500_when_redis_is_down(client, doctor, redis_down):
    redis_down()

    resp = await bad_login(client, doctor.email)

    assert resp.status_code == 401


async def test_A9_audit_login_success_has_user_id(client, doctor, audit):
    await client.post(URL, json={"email": doctor.email, "password": doctor.password})

    rows = await audit("login_success")
    assert [r["user_id"] for r in rows] == [doctor.id]


async def test_A9_failed_login_is_audited_despite_401(client, doctor, audit):
    await bad_login(client, doctor.email)
    await bad_login(client, "ghost@example.com")

    rows = await audit("login_failed")
    assert sorted(r["user_id"] or 0 for r in rows) == [0, doctor.id]  # NULL for unknown account


async def test_A9_blocked_login_is_audited_and_audit_has_no_email(client, doctor, audit):
    for _ in range(5):
        await bad_login(client, doctor.email)
    await client.post(URL, json={"email": doctor.email, "password": doctor.password})  # blocked

    assert len(await audit("login_blocked")) >= 1
    dump = str(await audit()).lower()
    assert doctor.email.lower() not in dump
    assert "example.com" not in dump


@pytest.mark.parametrize("body", [{}, {"email": "not-an-email", "password": "x"}, {"email": "a1@example.com"}])
async def test_login_validation_422(client, body):
    assert (await client.post(URL, json=body)).status_code == 422


async def test_json_login_does_not_set_cookies(client, doctor):
    resp = await client.post(URL, json={"email": doctor.email, "password": doctor.password})
    assert "set-cookie" not in resp.headers
