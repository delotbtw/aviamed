"""Spec section 6, block H (H-1..H-8, H-14, H-15): login/logout pages, cookies, session refresh, CSRF.

Form contract assumed (spec 5 gives no field names): POST /login form fields `email`, `password`, optional
`next` (sent both as a hidden field and in the query string, as a browser form would do either way).
"""

import pytest

from app.core.config import get_settings
from tests.helpers import STRONG_PASSWORD, cookie_attrs, location, set_cookie_headers, sha256


async def web_login(client, user, password=None, next_=None):
    data = {"email": user.email, "password": password or user.password}
    url = "/login"
    if next_ is not None:
        data["next"] = next_
        url = f"/login?next={next_}"
    return await client.post(url, data=data)


async def test_H1_login_page_has_form(client):
    resp = await client.get("/login")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert "<form" in html and 'name="email"' in html and 'name="password"' in html
    assert 'type="password"' in html


async def test_H1_logged_in_user_is_redirected_to_cabinet(client, doctor):
    await web_login(client, doctor)

    resp = await client.get("/login")

    assert resp.status_code == 303 and location(resp) == "/cabinet"


async def test_H2_login_success_redirects_and_sets_both_cookies(client, doctor, sql):
    resp = await web_login(client, doctor)

    assert resp.status_code == 303
    assert location(resp) == "/cabinet"
    cookies = set_cookie_headers(resp)
    assert "access_token" in cookies and "refresh_token" in cookies
    rows = await sql("SELECT id FROM refresh_tokens WHERE user_id = :u", u=doctor.id)
    assert len(rows) == 1
    assert (await client.get("/cabinet")).status_code == 200


async def test_H2_login_honours_relative_next(client, registrar):
    resp = await web_login(client, registrar, next_="/cabinet/athletes/new")

    assert resp.status_code == 303 and location(resp) == "/cabinet/athletes/new"


@pytest.mark.parametrize("variant", ["wrong_password", "unknown_email"])
async def test_H3_bad_credentials_show_error_without_cookies(client, doctor, variant):
    email = doctor.email if variant == "wrong_password" else "ghost1@example.com"
    resp = await client.post("/login", data={"email": email, "password": "Wrong-Passw0rd"})

    assert resp.status_code == 401
    assert "text/html" in resp.headers["content-type"]
    assert "Неверный email или пароль" in resp.text
    assert "set-cookie" not in resp.headers


async def test_H3_rate_limited_login_page_is_429_with_message(client, doctor):
    for _ in range(5):
        await client.post("/login", data={"email": doctor.email, "password": "Wrong-Passw0rd"})

    resp = await client.post("/login", data={"email": doctor.email, "password": doctor.password})

    assert resp.status_code == 429
    assert "Слишком много попыток" in resp.text
    assert "set-cookie" not in resp.headers


async def test_H4_cookie_flags_in_production_mode(client, doctor):
    resp = await web_login(client, doctor)
    s = get_settings()
    cookies = set_cookie_headers(resp)

    access = cookie_attrs(cookies["access_token"])
    assert access["httponly"] is True and access["secure"] is True
    assert access["samesite"].lower() == "lax" and access["path"] == "/"
    assert int(access["max-age"]) == s.access_token_ttl_min * 60

    refresh = cookie_attrs(cookies["refresh_token"])
    assert refresh["httponly"] is True and refresh["secure"] is True
    assert refresh["samesite"].lower() == "lax" and refresh["path"] == "/auth"
    assert int(refresh["max-age"]) == s.refresh_token_ttl_days * 86400


async def test_H4_secure_flag_is_off_in_debug_mode(client, doctor, monkeypatch):
    monkeypatch.setattr(get_settings(), "debug", True)

    resp = await web_login(client, doctor)

    cookies = set_cookie_headers(resp)
    assert set(cookies) == {"access_token", "refresh_token"}
    for raw in cookies.values():
        assert "secure" not in cookie_attrs(raw)


async def test_H5_logout_revokes_refresh_clears_cookies_and_ends_session(client, doctor, sql):
    login = await web_login(client, doctor)
    refresh_raw = set_cookie_headers(login)["refresh_token"].split(";")[0].split("=", 1)[1]
    # refresh cookie has Path=/auth, so the browser would not send it to /logout: the spec still requires revoking it,
    # hence the client must send it explicitly here.
    client.cookies.set("refresh_token", refresh_raw, path="/logout")

    resp = await client.post("/logout")

    assert resp.status_code == 303 and location(resp) == "/login"
    cookies = set_cookie_headers(resp)
    for name in ("access_token", "refresh_token"):
        assert int(cookie_attrs(cookies[name])["max-age"]) == 0
    [row] = await sql("SELECT revoked_at FROM refresh_tokens WHERE token_hash = :h", h=sha256(refresh_raw))
    assert row["revoked_at"] is not None
    client.cookies.clear()
    hop1 = await client.get("/cabinet")
    hop2 = await client.get(hop1.headers["location"])
    assert location(hop2).startswith("/login")


async def test_H5_logout_requires_authentication(client):
    resp = await client.post("/logout")

    assert resp.status_code in (303, 401)
    assert resp.status_code != 303 or "/login" in location(resp) or "/auth/session" in location(resp)


async def test_H6_cabinet_without_cookies_goes_through_auth_session_to_login(client):
    first = await client.get("/cabinet")
    assert first.status_code == 303 and location(first) == "/auth/session?next=/cabinet"

    second = await client.get(first.headers["location"])

    assert second.status_code == 303 and location(second) == "/login?next=/cabinet"


async def test_H7_expired_access_with_valid_refresh_rotates_session(client, doctor, login, sql, expired_token):
    pair = await login(client, doctor)
    client.cookies.clear()
    client.cookies.set("access_token", expired_token(doctor), path="/")
    client.cookies.set("refresh_token", pair["refresh_token"], path="/auth")

    first = await client.get("/cabinet")
    assert first.status_code == 303 and location(first) == "/auth/session?next=/cabinet"
    second = await client.get(first.headers["location"])

    assert second.status_code == 303 and location(second) == "/cabinet"
    cookies = set_cookie_headers(second)
    assert "access_token" in cookies and "refresh_token" in cookies
    new_refresh = cookies["refresh_token"].split(";")[0].split("=", 1)[1]
    assert new_refresh != pair["refresh_token"]
    [old] = await sql("SELECT revoked_at FROM refresh_tokens WHERE token_hash = :h", h=sha256(pair["refresh_token"]))
    assert old["revoked_at"] is not None
    assert (await client.get("/cabinet")).status_code == 200


async def test_H7_auth_session_with_garbage_refresh_goes_to_login(client):
    client.cookies.set("refresh_token", "garbage", path="/auth")

    resp = await client.get("/auth/session?next=/cabinet")

    assert resp.status_code == 303 and location(resp).startswith("/login")


@pytest.mark.parametrize("evil", ["//evil.com", "https://evil.com", "///evil.com", "/\\evil.com"])
async def test_H8_auth_session_ignores_unsafe_next(client, doctor, login, evil):
    pair = await login(client, doctor)
    client.cookies.set("refresh_token", pair["refresh_token"], path="/auth")

    resp = await client.get("/auth/session", params={"next": evil})

    assert resp.status_code == 303
    assert location(resp) == "/cabinet"


@pytest.mark.parametrize("evil", ["//evil.com", "https://evil.com"])
async def test_H8_login_ignores_unsafe_next(client, doctor, evil):
    resp = await client.post(
        "/login", params={"next": evil}, data={"email": doctor.email, "password": doctor.password, "next": evil}
    )

    assert resp.status_code == 303
    assert location(resp) == "/cabinet"


@pytest.mark.parametrize("evil", ["//evil.com", "https://evil.com"])
async def test_H8_auth_session_without_refresh_never_redirects_to_foreign_host(client, evil):
    resp = await client.get("/auth/session", params={"next": evil})

    assert resp.status_code == 303
    assert "evil.com" not in location(resp)


async def test_H14_post_with_foreign_origin_is_403(client, doctor, web_session):
    web_session(client, doctor)

    resp = await client.post(
        "/cabinet/password",
        data={"old_password": doctor.password, "new_password": STRONG_PASSWORD, "new_password_repeat": STRONG_PASSWORD},
        headers={"Origin": "https://evil.example"},
    )

    assert resp.status_code == 403
    login = await client.post("/auth/login", json={"email": doctor.email, "password": doctor.password})
    assert login.status_code == 200  # password unchanged


@pytest.mark.parametrize("origin", [None, "https://test"], ids=["no_origin", "same_origin"])
async def test_H14_post_without_or_with_same_origin_passes(client, doctor, web_session, origin):
    web_session(client, doctor)
    headers = {"Origin": origin} if origin else {}

    resp = await client.post(
        "/cabinet/password",
        data={"old_password": doctor.password, "new_password": STRONG_PASSWORD, "new_password_repeat": STRONG_PASSWORD},
        headers=headers,
    )

    assert resp.status_code == 303


async def test_H15_htmx_request_with_expired_access_gets_401_and_hx_redirect(client, doctor, expired_token):
    client.cookies.set("access_token", expired_token(doctor), path="/")

    resp = await client.get("/cabinet", headers={"HX-Request": "true"})

    assert resp.status_code == 401
    assert resp.headers["HX-Redirect"].replace("%2F", "/") == "/auth/session?next=/cabinet"


async def test_pages_use_russian_and_extend_base(client):
    resp = await client.get("/login")

    assert 'lang="ru"' in resp.text and "htmx" in resp.text.lower() and "alpine" in resp.text.lower()
