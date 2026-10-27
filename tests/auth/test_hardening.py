"""Review round 1: concurrency, hashing, JWT parsing, error bodies. Not tied to a spec criterion id."""

import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Response

from app.core.config import get_settings
from app.core.rbac import Action, Role, roles_for
from app.core.security import Argon2PasswordHasher
from app.core.web import clear_auth_cookies
from tests.helpers import cookie_attrs


async def test_parallel_wrong_passwords_cannot_exceed_the_account_limit(client, doctor):
    async def attempt():
        return (
            await client.post("/auth/login", json={"email": doctor.email, "password": "Wrong-Passw0rd"})
        ).status_code

    codes = await asyncio.gather(*(attempt() for _ in range(12)))

    assert sorted(codes) == [401] * 5 + [429] * 7


async def test_parallel_refresh_of_one_token_succeeds_only_once(client, doctor, login, sql):
    token = (await login(client, doctor))["refresh_token"]

    resps = await asyncio.gather(*(client.post("/auth/refresh", json={"refresh_token": token}) for _ in range(2)))

    assert sorted(r.status_code for r in resps) == [200, 401]
    active = await sql("SELECT id FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL", u=doctor.id)
    assert active == []  # the loser is treated as a replay and ends every session


async def test_verify_tolerates_garbage_hash():
    hasher = Argon2PasswordHasher()
    assert await hasher.verify("whatever", "not-a-valid-hash") is False
    assert await hasher.verify("whatever", "") is False


async def test_async_hasher_roundtrip_and_dummy():
    hasher = Argon2PasswordHasher()
    hashed = await hasher.hash("Passw0rd-Test")

    assert hashed.startswith("$argon2")
    assert await hasher.verify("Passw0rd-Test", hashed) is True
    assert await hasher.verify("other", hashed) is False
    assert await hasher.verify_dummy("anything") is None


@pytest.mark.parametrize("field", ["password", "old_password"])
async def test_oversized_password_is_422_and_not_echoed(client, doctor, field):
    huge = "A1" * 100
    if field == "password":
        resp = await client.post("/auth/login", json={"email": doctor.email, "password": huge})
    else:
        resp = await client.post(
            "/auth/change-password",
            json={"old_password": huge, "new_password": "Str0ng-Passw0rd"},
            headers=doctor.headers,
        )

    assert resp.status_code == 422
    assert huge not in resp.text


async def test_validation_error_does_not_echo_weak_password(client, admin):
    weak = "short1"
    payload = {"email": "x1@example.com", "password": weak, "role": "registrar", "last_name": "A", "first_name": "B"}

    resp = await client.post("/users", json=payload, headers=admin.headers)

    assert resp.status_code == 422
    assert weak not in resp.text


def _jwt(payload: dict) -> str:
    s = get_settings()
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


async def test_token_without_exp_or_with_bad_sub_is_401(client, doctor):
    exp = datetime.now(UTC) + timedelta(minutes=5)
    no_exp = _jwt({"sub": str(doctor.id), "type": "access"})
    bad_sub = _jwt({"sub": "not-a-number", "type": "access", "exp": exp})
    no_sub = _jwt({"type": "access", "exp": exp})

    for token in (no_exp, bad_sub, no_sub):
        resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


async def test_401_carries_www_authenticate(client):
    resp = await client.get("/users/me")

    assert resp.status_code == 401 and resp.headers["WWW-Authenticate"] == "Bearer"


async def test_logout_without_token_is_422(client):
    assert (await client.post("/auth/logout")).status_code == 422


async def test_logout_reads_refresh_token_from_cookie(client, doctor, login, sql):
    token = (await login(client, doctor))["refresh_token"]
    client.cookies.set("refresh_token", token, path="/auth")

    resp = await client.post("/auth/logout")

    assert resp.status_code == 204
    rows = await sql("SELECT revoked_at FROM refresh_tokens WHERE user_id = :u", u=doctor.id)
    assert rows[0]["revoked_at"] is not None


def test_deactivate_action_is_admin_only():
    assert roles_for(Action.USER_DEACTIVATE) == frozenset({Role.ADMIN})


@pytest.mark.parametrize(("debug", "secure"), [(False, True), (True, False)])
def test_cleared_cookies_keep_the_attributes_they_were_set_with(debug, secure):
    response = Response()
    settings = get_settings().model_copy(update={"debug": debug})

    clear_auth_cookies(response, settings)

    cookies = {raw.split("=", 1)[0]: raw for raw in response.headers.getlist("set-cookie")}
    for name, path in (("access_token", "/"), ("refresh_token", "/auth")):
        attrs = cookie_attrs(cookies[name])
        assert attrs["path"] == path and attrs["httponly"] is True and attrs["samesite"].lower() == "lax"
        assert int(attrs["max-age"]) == 0 and ("secure" in attrs) is secure


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "offset=-1"])
async def test_audit_pagination_bounds_are_422(client, admin, query):
    assert (await client.get(f"/audit?{query}", headers=admin.headers)).status_code == 422


async def test_audit_max_limit_is_accepted(client, admin):
    assert (await client.get("/audit?limit=500&offset=0", headers=admin.headers)).status_code == 200


def test_access_token_service_roundtrip_and_rejections():
    from datetime import timedelta

    import pytest

    from app.core.access_tokens import AccessTokenService, JwtCodec
    from app.core.exceptions import AuthenticationFailed

    tokens = AccessTokenService(JwtCodec("k" * 32, "HS256"), timedelta(minutes=5))
    other = AccessTokenService(JwtCodec("z" * 32, "HS256"), timedelta(minutes=5))

    claims = tokens.parse(tokens.issue(7, "doctor"))
    assert (claims.user_id, claims.role) == (7, "doctor")
    for bad in (
        "garbage",
        other.issue(7, "doctor"),
        JwtCodec("k" * 32, "HS256").encode({"sub": "1", "exp": 9999999999}),
    ):
        with pytest.raises(AuthenticationFailed):
            tokens.parse(bad)
