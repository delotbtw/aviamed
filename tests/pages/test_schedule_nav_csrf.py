"""Spec T-12..T-14 (menu texts: stage 2.1, 4.2.5): menu links by role, CSRF (Origin), HTMX session expiry."""

import pytest

from app.core.rbac import Role
from app.models.user import User
from app.web.nav import nav_links
from tests.schedule.support import HX, ORIGIN_EVIL

pytestmark = pytest.mark.usefixtures("schedule_invariants")

LINKS = {
    "/cabinet/schedule": {
        Role.ATHLETE: "Записаться на приём",
        Role.REGISTRAR: "Расписание и запись",
        Role.ADMIN: "Расписание и запись",
        Role.DOCTOR: "Свободные слоты",
    },
    "/cabinet/appointments": {
        Role.ATHLETE: "Моя запись",
        Role.REGISTRAR: "Очередь и приход",
        Role.ADMIN: "Очередь и приход",
    },
    "/cabinet/slots": {Role.ADMIN: "Слоты врачей", Role.REGISTRAR: "Слоты врачей", Role.DOCTOR: "Моё расписание"},
}


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("href", list(LINKS))
def test_T12_nav_links_by_role(role, href):
    shown = {link.href: link.label for link in nav_links(User(role=role))}

    if role in LINKS[href]:
        assert shown[href] == LINKS[href][role]
    else:
        assert href not in shown


@pytest.mark.parametrize("role", list(Role))
async def test_T12_cabinet_page_renders_the_links(client, clock, users_by_role, web_session, role):
    web_session(client, users_by_role[role])

    html = (await client.get("/cabinet")).text

    for href, labels in LINKS.items():
        if role in labels:
            assert f'href="{href}"' in html and f">{labels[role]}</a>" in html
        else:
            assert f'href="{href}"' not in html


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("/cabinet/schedule/book", {"slot_id": 1}),
        ("/cabinet/appointments/1/cancel", {}),
        ("/cabinet/appointments/1/arrive", {}),
        ("/cabinet/appointments/1/no-show", {}),
        ("/cabinet/slots/new", {"slot_date": "03.11.2026", "start_time": "09:00", "end_time": "10:00"}),
        ("/cabinet/slots/1/close", {}),
        ("/cabinet/slots/1/reopen", {}),
    ],
)
async def test_T13_foreign_origin_is_403(client, clock, admin, web_session, sql, path, data):
    web_session(client, admin)

    resp = await client.post(path, data=data, headers={**ORIGIN_EVIL, **HX})

    assert resp.status_code == 403
    assert await sql("SELECT id FROM slots") == [] and await sql("SELECT id FROM appointments") == []


@pytest.mark.parametrize("path", ["/cabinet/schedule", "/cabinet/appointments", "/cabinet/slots"])
async def test_T14_htmx_with_expired_access_gets_401_and_hx_redirect(client, clock, admin, expired_token, path):
    client.cookies.set("access_token", expired_token(admin), path="/")

    resp = await client.get(path, headers=HX)

    assert resp.status_code == 401
    assert resp.headers["HX-Redirect"].replace("%2F", "/") == f"/auth/session?next={path}"
