"""Stage 2.1 spec section 6.4 (F-1..F-3): no grey captions under headings, form callout, date fields."""

import pytest

from app.core.rbac import Role
from tests.helpers import athlete_payload
from tests.pages.dom import by_id, parse
from tests.schedule.support import HX

ATHLETES = "/cabinet/athletes/new"

PAGES = [
    (Role.ADMIN, "/cabinet/schedule"),
    (Role.ADMIN, "/cabinet/slots"),
    (Role.ADMIN, "/cabinet/appointments"),
    (Role.ATHLETE, "/cabinet/appointments"),
    (Role.ADMIN, ATHLETES),
    (Role.ADMIN, "/cabinet/users/new"),
    (Role.ADMIN, "/cabinet/password"),
]


@pytest.mark.parametrize(("role", "path"), PAGES)
async def test_F1_page_head_has_only_the_title(client, clock, users_by_role, web_session, role, path):
    web_session(client, users_by_role[role])

    root = parse((await client.get(path)).text)

    [head] = root.find_all("header", **{"class": "page-head"})
    assert [c.tag for c in head.children if not isinstance(c, str)] == ["h1"]
    assert not [n for n in root.walk() if "lead" in (n.attrs.get("class") or "") or "page-head__lead" in str(n.attrs)]


@pytest.mark.parametrize("path", ["/login", "/cabinet"])
async def test_F1_EXTRA_login_and_cabinet_start_have_no_caption(client, clock, admin, web_session, path):
    if path == "/cabinet":
        web_session(client, admin)

    root = parse((await client.get(path)).text)

    [head] = root.find_all("header", **{"class": "page-head"})
    assert [c.tag for c in head.children if not isinstance(c, str)] == ["h1"]


async def test_F2_athlete_form_has_no_format_hint_and_a_callout_after_the_form(client, registrar, web_session):
    web_session(client, registrar)

    resp = await client.get(ATHLETES)
    root = parse(resp.text)

    assert "Формат: дд.мм.гггг" not in resp.text
    callout = by_id(root, "form-callout")
    assert callout is not None and callout.tag == "aside" and callout.attrs.get("role") == "note"
    assert "парол" in callout.text.lower()
    order = [n for n in root.walk() if n.tag == "form" and n.find("input", name="last_name") or n is callout]
    assert order[0].tag == "form" and order[-1] is callout  # the callout follows the form in the DOM
    assert root.by_class("hint") == [] and root.find_all("small", **{"class": "hint"}) == []
    assert not [n for n in root.walk() if "h-" in (n.attrs.get("aria-describedby") or "")]


async def test_F2_errors_stay_linked_to_the_field(client, registrar, web_session):
    web_session(client, registrar)

    resp = await client.post(ATHLETES, data=athlete_payload(birth_date="31.02.2004"), headers=HX)

    root = parse(resp.text)
    assert resp.status_code == 422 and "Формат: дд.мм.гггг" not in resp.text
    assert by_id(root, "e-birth_date") is not None
    assert by_id(root, "f-birth_date").attrs["aria-describedby"] == "e-birth_date"


async def test_F3_date_field_is_a_masked_text_input(client, registrar, web_session):
    web_session(client, registrar)

    field = by_id(parse((await client.get(ATHLETES)).text), "f-birth_date")

    assert field.attrs["type"] == "text" and field.attrs["placeholder"] == "дд.мм.гггг"
