"""Spec stage 2 section 6 (T-9..T-11, Q-1/Q-5) and stage 2.1 section 6.2 (S-1..S-5): /cabinet/slots.

Slots are managed by admin and registrar; a doctor only reads his own schedule."""

import pytest

from app.core.rbac import Role
from tests.helpers import location
from tests.pages.dom import by_id, parse
from tests.schedule.support import HX, actions, at, element, has_element, input_tag, is_fragment, msk, row

pytestmark = pytest.mark.usefixtures("schedule_invariants")

URL = "/cabinet/slots"
NEW = "/cabinet/slots/new"
DATE_ERROR = "Введите существующую дату в формате дд.мм.гггг"
TIME_ERROR = "Введите время в формате чч:мм"


def form(**over) -> dict:
    return {"slot_date": "03.11.2026", "start_time": "09:00", "end_time": "12:00", "slot_minutes": "30", **over}


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.DOCTOR, 200), (Role.ADMIN, 200), (Role.REGISTRAR, 200), (Role.ATHLETE, 403), (Role.COACH, 403)],
)
async def test_T9_S4_access_by_role(client, clock, users_by_role, web_session, role, expected):
    web_session(client, users_by_role[role])

    assert (await client.get(URL)).status_code == expected


async def test_T9_without_cookie_redirects(client, clock):
    resp = await client.get(URL)

    assert resp.status_code == 303 and location(resp) == "/auth/session?next=/cabinet/slots"


async def test_T9_doctor_sees_only_own_slots_of_the_day_with_the_athlete_name(
    client, clock, doctor, doctor2, athlete2, make_slot, make_booking, web_session
):
    free = await make_slot(doctor, msk(2026, 11, 2, 12))
    taken = await make_slot(doctor, msk(2026, 11, 2, 13))
    await make_booking(taken, athlete2)
    closed = await make_slot(doctor, msk(2026, 11, 2, 14), status="closed")
    foreign = await make_slot(doctor2, msk(2026, 11, 2, 12))
    tomorrow = await make_slot(doctor, at(10))
    web_session(client, doctor)

    html = (await client.get(URL)).text

    assert has_element(html, "slots-manage-table")
    assert all(has_element(html, f"slot-{i}") for i in (free, taken, closed))
    assert not has_element(html, f"slot-{foreign}") and not has_element(html, f"slot-{tomorrow}")
    assert "Петров Пётр" in row(html, f"slot-{taken}")
    assert [row(html, f"slot-{i}").count('data-status="') for i in (free, taken, closed)] == [1, 1, 1]
    assert 'data-status="closed"' in row(html, f"slot-{closed}")
    assert not has_element(html, "f-doctor_id")  # a doctor does not choose a doctor
    assert not has_element(html, "f-slot_doctor_id")


async def test_T9_date_filter_uses_the_russian_format(client, clock, doctor, make_slot, web_session):
    tomorrow = await make_slot(doctor, at(10))
    web_session(client, doctor)

    ok = await client.get(URL, params={"date": "03.11.2026"})
    bad = await client.get(URL, params={"date": "3.11.2026"})

    assert has_element(ok.text, f"slot-{tomorrow}") and 'value="03.11.2026"' in input_tag(ok.text, "f-date")
    assert bad.status_code == 422 and DATE_ERROR in bad.text


@pytest.mark.parametrize("role", [Role.ADMIN, Role.REGISTRAR])
async def test_T9_S2_manager_sees_every_doctor_and_can_pick_one(
    client, clock, users_by_role, doctor, doctor2, make_slot, web_session, role
):
    a = await make_slot(doctor, msk(2026, 11, 2, 12))
    b = await make_slot(doctor2, msk(2026, 11, 2, 12))
    web_session(client, users_by_role[role])

    everyone = (await client.get(URL)).text
    only_second = (await client.get(URL, params={"doctor_id": doctor2.id})).text

    assert has_element(everyone, "f-doctor_id") and has_element(everyone, "f-slot_doctor_id")
    assert has_element(everyone, f"slot-{a}") and has_element(everyone, f"slot-{b}")
    assert has_element(only_second, f"slot-{b}") and not has_element(only_second, f"slot-{a}")


async def test_T11_S2_buttons_follow_the_slot_status(
    client, clock, registrar, doctor, athlete, make_slot, make_booking, web_session
):
    free = await make_slot(doctor, msk(2026, 11, 2, 12))
    taken = await make_slot(doctor, msk(2026, 11, 2, 13))
    await make_booking(taken, athlete)
    closed = await make_slot(doctor, msk(2026, 11, 2, 14), status="closed")
    web_session(client, registrar)

    html = (await client.get(URL)).text

    assert actions(row(html, f"slot-{free}")) == {"close"}
    assert actions(row(html, f"slot-{taken}")) == set()  # a booked slot cannot be closed from the page
    assert actions(row(html, f"slot-{closed}")) == {"reopen"}


async def test_T11_S3_close_and_reopen_from_the_page(client, clock, registrar, doctor, make_slot, web_session, sql):
    slot_id = await make_slot(doctor, at(10))
    web_session(client, registrar)

    closed = await client.post(f"{URL}/{slot_id}/close", headers=HX)
    reopened = await client.post(f"{URL}/{slot_id}/reopen", headers=HX)

    assert closed.status_code == 200 and is_fragment(closed.text)
    assert 'data-status="closed"' in row(closed.text, f"slot-{slot_id}")
    assert actions(row(closed.text, f"slot-{slot_id}")) == {"reopen"}
    assert reopened.status_code == 200 and 'data-status="free"' in row(reopened.text, f"slot-{slot_id}")
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "free"


async def test_T11_closing_a_booked_slot_is_409_with_text(
    client, clock, registrar, doctor, athlete, make_slot, make_booking, web_session, sql
):
    slot_id = await make_slot(doctor, at(10))
    await make_booking(slot_id, athlete)
    web_session(client, registrar)

    resp = await client.post(f"{URL}/{slot_id}/close", headers=HX)

    assert resp.status_code == 409 and "Слот занят, сначала отмените запись" in resp.text
    assert 'data-status="booked"' in row(resp.text, f"slot-{slot_id}")


@pytest.mark.parametrize("owner", ["own", "foreign"])
async def test_S4_doctor_cannot_close_or_reopen_any_slot(
    client, clock, doctor, doctor2, make_slot, web_session, sql, owner
):
    slot_id = await make_slot(doctor if owner == "own" else doctor2, at(10))
    closed_id = await make_slot(doctor, at(12), status="closed")
    web_session(client, doctor)

    close = await client.post(f"{URL}/{slot_id}/close", headers=HX)
    reopen = await client.post(f"{URL}/{closed_id}/reopen", headers=HX)

    assert close.status_code == 403 and reopen.status_code == 403  # a 403 page, not 404
    assert {r["id"]: r["status"] for r in await sql("SELECT id, status FROM slots")} == {
        slot_id: "free",
        closed_id: "closed",
    }
    assert await sql("SELECT id FROM audit_log WHERE action LIKE 'slot.%'") == []


@pytest.mark.parametrize("role", [Role.ATHLETE, Role.COACH])
async def test_T11_other_roles_cannot_post(client, clock, users_by_role, doctor, make_slot, web_session, role):
    slot_id = await make_slot(doctor, at(10))
    web_session(client, users_by_role[role])

    assert (await client.post(f"{URL}/{slot_id}/close", headers=HX)).status_code == 403


@pytest.mark.parametrize("role", [Role.ADMIN, Role.REGISTRAR])
async def test_T11_manager_closes_any_slot(client, clock, users_by_role, doctor2, make_slot, web_session, role):
    slot_id = await make_slot(doctor2, at(10))
    web_session(client, users_by_role[role])

    assert (await client.post(f"{URL}/{slot_id}/close", headers=HX)).status_code == 200


async def test_T10_S2_form_creates_six_slots_and_Q1_stores_utc(client, clock, registrar, doctor, web_session, sql):
    web_session(client, registrar)

    resp = await client.post(NEW, data=form(slot_doctor_id=doctor.id), headers=HX)

    assert resp.status_code == 200 and is_fragment(resp.text)
    assert "Создано слотов: 6" in element(resp.text, "div", "slots-result")
    assert has_element(resp.text, "slots-manage-table")
    rows = await sql(
        "SELECT to_char(start_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI') AS s FROM slots ORDER BY start_at"
    )
    assert [r["s"] for r in rows] == [
        "2026-11-03 06:00",
        "2026-11-03 06:30",
        "2026-11-03 07:00",
        "2026-11-03 07:30",
        "2026-11-03 08:00",
        "2026-11-03 08:30",
    ]
    assert {r["created_by"] for r in await sql("SELECT created_by FROM slots")} == {registrar.id}
    assert {r["doctor_id"] for r in await sql("SELECT doctor_id FROM slots")} == {doctor.id}


async def test_Q1_slot_created_from_the_page_is_shown_in_moscow_time(
    client, clock, registrar, doctor, web_session, sql
):
    web_session(client, registrar)

    resp = await client.post(
        NEW, data=form(slot_doctor_id=doctor.id, start_time="10:30", end_time="11:00", slot_minutes=""), headers=HX
    )

    assert resp.status_code == 200 and "Создано слотов: 1" in resp.text
    [slot] = await sql("SELECT to_char(start_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS s, id FROM slots")
    assert slot["s"] == "2026-11-03 07:30:00"
    page = (await client.get(URL, params={"date": "03.11.2026"})).text
    shown = row(page, f"slot-{slot['id']}")
    assert "10:30" in shown and "07:30" not in shown


async def test_T10_empty_length_creates_one_slot_for_the_whole_window(
    client, clock, registrar, doctor, web_session, sql
):
    web_session(client, registrar)

    resp = await client.post(NEW, data=form(slot_doctor_id=doctor.id, slot_minutes=""), headers=HX)

    assert resp.status_code == 200 and "Создано слотов: 1" in resp.text
    [slot] = await sql("SELECT start_at, end_at FROM slots")
    assert (slot["end_at"] - slot["start_at"]).total_seconds() == 3 * 3600


@pytest.mark.parametrize("role", [Role.ADMIN, Role.REGISTRAR])
async def test_T10_S2_manager_must_pick_a_doctor_and_then_creates_for_him(
    client, clock, users_by_role, doctor2, web_session, sql, role
):
    web_session(client, users_by_role[role])

    missing = await client.post(NEW, data=form(), headers=HX)
    ok = await client.post(NEW, data=form(slot_doctor_id=doctor2.id), headers=HX)

    assert missing.status_code == 422 and "Выберите врача" in element(missing.text, "small", "e-slot_doctor_id")
    assert ok.status_code == 200
    assert {r["doctor_id"] for r in await sql("SELECT doctor_id FROM slots")} == {doctor2.id}


@pytest.mark.parametrize("target", ["none", "self", "other"])
async def test_S4_doctor_cannot_create_slots_at_all(client, clock, doctor, doctor2, web_session, sql, target):
    web_session(client, doctor)
    extra = {"self": {"slot_doctor_id": doctor.id}, "other": {"slot_doctor_id": doctor2.id}}.get(target, {})

    resp = await client.post(NEW, data=form(**extra), headers=HX)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM slots") == []
    assert await sql("SELECT id FROM audit_log WHERE action LIKE 'slot.%'") == []


@pytest.mark.parametrize(
    ("over", "field", "message"),
    [
        ({"slot_date": "31.02.2026"}, "slot_date", DATE_ERROR),
        ({"slot_date": "3.11.2026"}, "slot_date", DATE_ERROR),
        ({"start_time": "9:00"}, "start_time", TIME_ERROR),
        ({"end_time": "24:00"}, "end_time", TIME_ERROR),
        ({"start_time": "12:00", "end_time": "09:00"}, "end_time", "Окончание должно быть позже начала"),
        (
            {"slot_date": "02.11.2026", "start_time": "08:00", "end_time": "08:30", "slot_minutes": ""},
            "start_time",
            "Время начала должно быть в будущем",
        ),
        ({"slot_minutes": "abc"}, "slot_minutes", "Введите длину слота в минутах (целое число)"),
    ],
    ids=["no-such-date", "one-digit-day", "one-digit-hour", "hour-24", "end-before-start", "past", "minutes-text"],
)
async def test_T10_validation_errors_are_shown_under_the_field_and_values_come_back(
    client, clock, registrar, doctor, web_session, sql, over, field, message
):
    web_session(client, registrar)
    data = form(slot_doctor_id=doctor.id, **over)

    resp = await client.post(NEW, data=data, headers=HX)

    assert resp.status_code == 422 and is_fragment(resp.text)
    assert message in element(resp.text, "small", f"e-{field}")
    for name, typed in data.items():  # Q-5: the same дд.мм.гггг / чч:мм text is returned
        if typed and name != "slot_doctor_id":
            assert f'value="{typed}"' in input_tag(resp.text, f"f-{name}")
    assert await sql("SELECT id FROM slots") == []


async def test_T10_overlap_is_a_general_409_message_and_keeps_the_values(
    client, clock, registrar, doctor, make_slot, web_session, sql
):
    await make_slot(doctor, at(10), minutes=30)
    web_session(client, registrar)

    resp = await client.post(
        NEW, data=form(slot_doctor_id=doctor.id, start_time="10:15", end_time="10:45", slot_minutes=""), headers=HX
    )

    assert resp.status_code == 409 and "Слот пересекается с уже существующим" in resp.text
    assert 'value="03.11.2026"' in input_tag(resp.text, "f-slot_date") and 'value="10:15"' in input_tag(
        resp.text, "f-start_time"
    )
    assert len(await sql("SELECT id FROM slots")) == 1


async def test_T10_one_conflict_rolls_back_the_whole_batch_from_the_page(
    client, clock, registrar, doctor, make_slot, web_session, sql
):
    await make_slot(doctor, at(10, 30), minutes=30)
    web_session(client, registrar)

    resp = await client.post(NEW, data=form(slot_doctor_id=doctor.id), headers=HX)

    assert resp.status_code == 409
    assert len(await sql("SELECT id FROM slots")) == 1


@pytest.mark.parametrize("role", [Role.ATHLETE, Role.COACH])
async def test_T10_other_roles_cannot_post_the_form(client, clock, users_by_role, web_session, sql, role):
    web_session(client, users_by_role[role])

    assert (await client.post(NEW, data=form(), headers=HX)).status_code == 403
    assert await sql("SELECT id FROM slots") == []


async def test_T10_form_fields_are_text_inputs_with_masks(client, clock, registrar, web_session):
    web_session(client, registrar)

    html = (await client.get(URL)).text

    assert has_element(html, "slot-form") and 'hx-post="/cabinet/slots/new"' in html
    for field, placeholder in (("f-slot_date", "дд.мм.гггг"), ("f-start_time", "чч:мм"), ("f-end_time", "чч:мм")):
        tag = input_tag(html, field)
        assert 'type="text"' in tag and f'placeholder="{placeholder}"' in tag
    assert has_element(html, "f-slot_minutes")


# --------------------------------------------------------------------------- stage 2.1, section 6.2


async def test_S1_doctor_page_is_read_only(client, clock, doctor, doctor2, make_slot, web_session):
    own = await make_slot(doctor, at(10))
    closed = await make_slot(doctor, at(12), status="closed")
    await make_slot(doctor2, at(10))
    web_session(client, doctor)

    resp = await client.get(URL, params={"date": "03.11.2026"})  # the slots are made for tomorrow
    html = resp.text

    assert resp.status_code == 200 and has_element(html, "slots-manage-table")
    assert has_element(html, f"slot-{own}") and has_element(html, f"slot-{closed}")
    assert not has_element(html, "slot-form") and not has_element(html, "slot-add")
    assert not has_element(html, "f-doctor_id") and not has_element(html, "f-slot_doctor_id")
    assert actions(html) == set()  # no close/reopen buttons anywhere


async def test_S2_registrar_page_has_filter_form_and_buttons(client, clock, registrar, doctor, make_slot, web_session):
    free = await make_slot(doctor, msk(2026, 11, 2, 12))
    closed = await make_slot(doctor, msk(2026, 11, 2, 14), status="closed")
    web_session(client, registrar)

    html = (await client.get(URL)).text

    assert has_element(html, "f-doctor_id") and has_element(html, "slot-form") and has_element(html, "f-slot_doctor_id")
    assert actions(row(html, f"slot-{free}")) == {"close"} and actions(row(html, f"slot-{closed}")) == {"reopen"}


async def test_S2_registrar_creation_reports_the_count(client, clock, registrar, doctor, web_session):
    web_session(client, registrar)

    resp = await client.post(NEW, data=form(slot_doctor_id=doctor.id), headers=HX)

    assert resp.status_code == 200 and "Создано слотов: 6" in element(resp.text, "div", "slots-result")


@pytest.mark.parametrize("role", [Role.ADMIN, Role.REGISTRAR])
async def test_S5_add_card_is_a_section_apart_from_the_filter_bar(client, clock, users_by_role, web_session, role):
    web_session(client, users_by_role[role])

    root = parse((await client.get(URL)).text)

    card = by_id(root, "slot-add")
    assert card is not None and card.tag == "section" and "card" in card.attrs["class"].split()
    assert card.find("h2") is not None and card.find("h2").text == "Добавить слоты"
    assert any("btn-primary" in b.attrs.get("class", "").split() for b in card.find_all("button"))
    bar = by_id(root, "slots-filter")
    assert bar is not None and bar.tag == "form" and not bar.inside(card)
    assert by_id(root, "slot-form") is not None and by_id(root, "slot-form").inside(card)
