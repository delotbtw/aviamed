"""Round 3: lock order (users -> refresh_tokens), limiter details, audit volume."""

import asyncio

from tests.helpers import STRONG_PASSWORD


async def test_parallel_logout_refresh_and_deactivate_do_not_deadlock(client, admin, doctor, login):
    for _ in range(6):
        token = (await login(client, doctor))["refresh_token"]
        results = await asyncio.gather(
            client.post("/auth/logout", json={"refresh_token": token}),
            client.post("/auth/refresh", json={"refresh_token": token}),
            client.post("/auth/logout", json={"refresh_token": token}),
        )
        assert all(r.status_code in (200, 204, 401) for r in results), [r.status_code for r in results]

    token = (await login(client, doctor))["refresh_token"]
    results = await asyncio.gather(
        client.post("/auth/logout", json={"refresh_token": token}),
        client.post(f"/users/{doctor.id}/deactivate", headers=admin.headers),
        client.post("/auth/refresh", json={"refresh_token": token}),
        client.post(
            "/auth/change-password",
            json={"old_password": doctor.password, "new_password": STRONG_PASSWORD},
            headers=doctor.headers,
        ),
    )
    assert all(r.status_code < 500 for r in results), [r.status_code for r in results]


async def test_parallel_login_and_deactivate_leave_no_usable_session(client, admin, doctor, sql):
    results = await asyncio.gather(
        client.post("/auth/login", json={"email": doctor.email, "password": doctor.password}),
        client.post(f"/users/{doctor.id}/deactivate", headers=admin.headers),
    )

    assert all(r.status_code < 500 for r in results)
    active = await sql("SELECT id FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL", u=doctor.id)
    assert active == []  # either login lost (401) or deactivation revoked the new token


async def test_blocked_attempts_write_one_audit_record_per_block(client, doctor, audit):
    for _ in range(5):
        await client.post("/auth/login", json={"email": doctor.email, "password": "Wrong-Passw0rd"})
    for _ in range(4):
        resp = await client.post("/auth/login", json={"email": doctor.email, "password": doctor.password})
        assert resp.status_code == 429

    assert len(await audit("login_blocked")) == 1


async def test_rejected_new_passwords_do_not_consume_login_attempts(client, doctor):
    for weak in ("short", "abcdefghijkl", doctor.password):
        resp = await client.post(
            "/auth/change-password",
            json={"old_password": doctor.password, "new_password": weak},
            headers=doctor.headers,
        )
        assert resp.status_code == 422
    for _ in range(5):
        await client.post(
            "/auth/change-password",
            json={"old_password": doctor.password, "new_password": doctor.password},
            headers=doctor.headers,
        )

    login = await client.post("/auth/login", json={"email": doctor.email, "password": doctor.password})
    assert login.status_code == 200


async def test_ip_counter_release_never_creates_a_negative_key(client, doctor, redis):
    await client.post("/auth/login", json={"email": doctor.email, "password": doctor.password})  # reserve + release
    await redis.flushall()  # window expired between the reservation and the release
    from app.auth.rate_limit import RedisAttemptLimiter

    limiter = RedisAttemptLimiter(redis, max_attempts=5, max_attempts_ip=20, window_s=900)
    await limiter.release_success("x@example.com", "10.0.0.1")

    assert await redis.keys("login:ip:*") == []


async def test_parallel_password_changes_apply_exactly_once(client, doctor, sql):
    body = {"old_password": doctor.password, "new_password": STRONG_PASSWORD}

    resps = await asyncio.gather(
        *(client.post("/auth/change-password", json=body, headers=doctor.headers) for _ in range(3))
    )

    codes = sorted(r.status_code for r in resps)
    assert codes.count(204) == 1 and all(c in (204, 400, 409) for c in codes), codes
    login = await client.post("/auth/login", json={"email": doctor.email, "password": STRONG_PASSWORD})
    assert login.status_code == 200


async def test_cross_deactivations_between_admins_do_not_deadlock(client, admin, make_user, sql):
    from app.core.rbac import Role

    a, b, c = admin, await make_user(Role.ADMIN), await make_user(Role.ADMIN)
    rings = [[(a, b), (b, a)], [(a, b), (b, c), (c, a)]]
    for _ in range(5):
        for ring in rings:
            await sql("UPDATE users SET is_active = true")
            results = await asyncio.gather(
                *(client.post(f"/users/{target.id}/deactivate", headers=actor.headers) for actor, target in ring)
            )
            # an actor deactivated first loses access (401), the rest succeed; never a deadlock (500)
            assert all(r.status_code in (204, 401) for r in results), [r.status_code for r in results]


async def test_user_row_lock_does_not_block_foreign_key_checks(db_engine, doctor):
    """get_for_update must be FOR NO KEY UPDATE: FOR KEY SHARE (taken by FK checks) is still granted, writers wait."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.repositories.user import UserRepository

    async with AsyncSession(db_engine) as holder, db_engine.connect() as other:
        await UserRepository(holder).get_for_update(doctor.id)
        key_share = await other.execute(
            text("SELECT id FROM users WHERE id = :i FOR KEY SHARE NOWAIT"), {"i": doctor.id}
        )
        assert key_share.scalar() == doctor.id
        await other.rollback()
        try:
            await other.execute(text("SELECT id FROM users WHERE id = :i FOR NO KEY UPDATE NOWAIT"), {"i": doctor.id})
            raise AssertionError("a second writer lock must not be granted")
        except DBAPIError:
            pass
        await holder.rollback()


async def test_slow_redis_release_after_login_does_not_hold_the_user_lock(client, doctor, monkeypatch):
    import time

    from app.auth.rate_limit import RedisAttemptLimiter

    original = RedisAttemptLimiter.release_success

    async def slow_release(self, email, ip, *, count_ip=True):
        if count_ip:  # the login path only
            await asyncio.sleep(2.0)
        await original(self, email, ip, count_ip=count_ip)

    monkeypatch.setattr(RedisAttemptLimiter, "release_success", slow_release)
    login = asyncio.create_task(client.post("/auth/login", json={"email": doctor.email, "password": doctor.password}))
    await asyncio.sleep(0.6)  # login has committed and is now waiting for Redis

    started = time.monotonic()
    resp = await client.post(
        "/auth/change-password",
        json={"old_password": doctor.password, "new_password": STRONG_PASSWORD},
        headers=doctor.headers,
    )
    elapsed = time.monotonic() - started

    assert resp.status_code == 204 and elapsed < 1.2, elapsed
    assert (await login).status_code == 200


def test_redis_client_has_socket_timeouts(monkeypatch):
    import app.core.redis as redis_module
    from app.core.redis import REDIS_TIMEOUT_S, get_redis

    monkeypatch.setattr(redis_module, "_redis", None)  # build the real (lazy, unconnected) client, restore afterwards
    pool = get_redis().connection_pool.connection_kwargs
    assert pool["socket_timeout"] == REDIS_TIMEOUT_S and pool["socket_connect_timeout"] == REDIS_TIMEOUT_S
