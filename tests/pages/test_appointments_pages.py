"""Spec section 6, T-7 and T-8: /cabinet/appointments (athlete: "Моя запись", staff: queue) and row actions."""

import pytest

from app.core.rbac import Role
from tests.helpers import location
from tests.schedule.support import HX, actions, at, element, has_element, is_fragment, msk, row

pytestmark = pytest.mark.usefixtures("schedule_invariants")

URL = "/cabinet/appointments"
TODAY_NOON = msk(2026, 11, 2, 12)


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.ADMIN, 200), (Role.REGISTRAR, 200), (Role.ATHLETE, 200), (Role.DOCTOR, 403), (Role.COACH, 403)],
)
async def test_T7_access_by_role(client, clock, users_by_role, web_session, role, expected):
    web_session(client, users_by_role[role])

    assert (await client.get(URL)).status_code == expected


async def test_T7_without_cookie_redirects(client, clock):
    resp = await client.get(URL)

    assert resp.status_code == 303 and location(resp) == "/auth/session?next=/cabinet/appointments"


async def test_T7_athlete_sees_own_upcoming_and_history_but_not_others(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking, force_status, web_session
):
    upcoming = await make_booking(await make_slot(doctor, at(10)), athlete)
    cancelled = await make_booking(await make_slot(doctor, at(12)), athlete)
    await force_status(cancelled, "cancelled")
    foreign = await make_booking(await make_slot(doctor, at(14)), athlete2)
    web_session(client, athlete)

    html = (await client.get(URL)).text

    assert "Моя запись" in html
    assert has_element(element(html, "section", "upcoming-appointments"), f"appt-{upcoming}")
    assert has_element(element(html, "section", "appointment-history"), f"appt-{cancelled}")
    assert not has_element(html, f"appt-{foreign}")
    shown = row(html, f"appt-{upcoming}")
    assert "03.11.2026" in shown and "10:00" in shown and 'data-status="booked"' in shown
    assert actions(shown) == {"cancel"} and "confirm(" in shown
    assert actions(row(html, f"appt-{cancelled}")) == set()


async def test_T7_athlete_cannot_cancel_after_the_start(
    client, clock, athlete, doctor, make_slot, make_booking, web_session
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    clock.set(at(10, 5))
    web_session(client, athlete)

    html = (await client.get(URL)).text

    assert actions(row(html, f"appt-{appointment_id}")) == set()


async def test_T7_registrar_queue_defaults_to_today_with_filters_in_the_markup(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, web_session
):
    today = await make_booking(await make_slot(doctor, TODAY_NOON), athlete)
    tomorrow = await make_booking(await make_slot(doctor, at(10)), athlete)
    web_session(client, registrar)

    html = (await client.get(URL)).text

    assert has_element(html, "queue-table") and has_element(html, f"appt-{today}")
    assert not has_element(html, f"appt-{tomorrow}")
    assert 'value="02.11.2026"' in element(html, "form", "queue-filters") and 'placeholder="дд.мм.гггг"' in html
    for field in ("f-date", "f-doctor_id", "f-status", "athlete-search"):
        assert has_element(html, field)
    other_day = (await client.get(URL, params={"date": "03.11.2026"})).text
    assert has_element(other_day, f"appt-{tomorrow}") and not has_element(other_day, f"appt-{today}")


async def test_T7_queue_filters_by_doctor_status_and_athlete(
    client, clock, registrar, athlete, athlete2, doctor, doctor2, make_slot, make_booking, force_status, web_session
):
    a = await make_booking(await make_slot(doctor, TODAY_NOON), athlete)
    b = await make_booking(await make_slot(doctor2, TODAY_NOON), athlete2)
    await force_status(b, "arrived")
    web_session(client, registrar)

    async def shown(**params):
        html = (await client.get(URL, params=params, headers=HX)).text
        return {n for n in (a, b) if has_element(html, f"appt-{n}")}

    assert await shown(doctor_id=doctor2.id) == {b}
    assert await shown(status="booked") == {a}
    assert await shown(athlete_id=athlete2.id) == {b}
    assert await shown() == {a, b}


async def test_T7_bad_queue_date_is_422(client, clock, registrar, web_session):
    web_session(client, registrar)

    resp = await client.get(URL, params={"date": "31.02.2026"})

    assert resp.status_code == 422 and "Введите существующую дату в формате дд.мм.гггг" in resp.text


async def test_T7_registrar_buttons_follow_the_status_and_the_time(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, force_status, web_session
):
    booked = await make_booking(await make_slot(doctor, msk(2026, 11, 2, 12), minutes=30), athlete)
    arrived = await make_booking(await make_slot(doctor, msk(2026, 11, 2, 13), minutes=30), athlete)
    await force_status(arrived, "arrived")
    cancelled = await make_booking(await make_slot(doctor, msk(2026, 11, 2, 14), minutes=30), athlete)
    await force_status(cancelled, "cancelled")
    web_session(client, registrar)

    before_end = (await client.get(URL)).text
    assert actions(row(before_end, f"appt-{booked}")) == {"arrive", "cancel"}  # no-show only after the end
    assert actions(row(before_end, f"appt-{arrived}")) == set()
    assert actions(row(before_end, f"appt-{cancelled}")) == set()

    clock.set(msk(2026, 11, 2, 12, 30))
    after_end = (await client.get(URL)).text
    assert actions(row(after_end, f"appt-{booked}")) == {
        "arrive",
        "no-show",
    }  # cancelling is over at the end of the slot
    assert "busy" in element(after_end, "tr", f"appt-{booked}")  # buttons are disabled while a request is in flight


async def test_T7_admin_sees_the_queue_without_arrival_buttons(
    client, clock, admin, athlete, doctor, make_slot, make_booking, web_session
):
    appointment_id = await make_booking(await make_slot(doctor, TODAY_NOON), athlete)
    web_session(client, admin)

    html = (await client.get(URL)).text

    assert actions(row(html, f"appt-{appointment_id}")) == {"cancel"}


async def test_T8_cancel_returns_the_updated_row_and_repeating_is_fine(
    client, clock, athlete, doctor, make_slot, make_booking, web_session, sql
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    web_session(client, athlete)

    first = await client.post(f"{URL}/{appointment_id}/cancel", headers=HX)
    again = await client.post(f"{URL}/{appointment_id}/cancel", headers=HX)

    for resp in (first, again):
        assert resp.status_code == 200 and is_fragment(resp.text)
        shown = row(resp.text, f"appt-{appointment_id}")
        assert 'data-status="cancelled"' in shown and actions(shown) == set()
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "cancelled"
    assert len(await sql("SELECT id FROM audit_log WHERE action = 'appointment_cancel'")) == 1


async def test_T8_cancel_of_a_started_slot_by_the_athlete_is_409_with_text(
    client, clock, athlete, doctor, make_slot, make_booking, web_session
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    clock.set(at(10, 1))
    web_session(client, athlete)

    resp = await client.post(f"{URL}/{appointment_id}/cancel", headers=HX)

    assert resp.status_code == 409 and "Приём уже начался, отмена невозможна" in resp.text
    assert 'data-status="booked"' in row(resp.text, f"appt-{appointment_id}")


async def test_T8_foreign_appointment_is_404_and_untouched(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking, web_session, sql
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    web_session(client, athlete2)

    resp = await client.post(f"{URL}/{appointment_id}/cancel", headers=HX)

    assert resp.status_code == 404 and "Запись не найдена" in resp.text
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


@pytest.mark.parametrize("role", [Role.DOCTOR, Role.COACH])
async def test_T8_doctor_and_coach_cannot_cancel(
    client, clock, users_by_role, athlete, doctor, make_slot, make_booking, web_session, role
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    web_session(client, users_by_role[role])

    assert (await client.post(f"{URL}/{appointment_id}/cancel", headers=HX)).status_code == 403


async def test_T8_arrive_updates_the_row_and_the_second_click_is_409(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, web_session, sql
):
    appointment_id = await make_booking(await make_slot(doctor, TODAY_NOON), athlete)
    web_session(client, registrar)

    first = await client.post(f"{URL}/{appointment_id}/arrive", headers=HX)
    again = await client.post(f"{URL}/{appointment_id}/arrive", headers=HX)

    assert first.status_code == 200 and 'data-status="arrived"' in row(first.text, f"appt-{appointment_id}")
    assert again.status_code == 409 and "Действие недоступно для текущего статуса записи" in again.text
    assert 'data-status="arrived"' in row(again.text, f"appt-{appointment_id}")  # the page is not broken
    assert len(await sql("SELECT id FROM audit_log WHERE action = 'appointment_arrive'")) == 1


async def test_T8_arrival_on_another_day_has_its_own_text(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, web_session
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    web_session(client, registrar)

    resp = await client.post(f"{URL}/{appointment_id}/arrive", headers=HX)

    assert resp.status_code == 409 and "Приход можно отметить только в день приёма" in resp.text


@pytest.mark.parametrize("role", [Role.ADMIN, Role.ATHLETE, Role.DOCTOR, Role.COACH])
@pytest.mark.parametrize("action", ["arrive", "no-show"])
async def test_T8_only_the_registrar_posts_arrival_and_no_show(
    client, clock, users_by_role, athlete, doctor, make_slot, make_booking, web_session, sql, role, action
):
    appointment_id = await make_booking(await make_slot(doctor, TODAY_NOON), athlete)
    web_session(client, users_by_role[role])

    resp = await client.post(f"{URL}/{appointment_id}/{action}", headers=HX)

    assert resp.status_code == 403
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


async def test_T8_no_show_after_the_end(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, web_session
):
    appointment_id = await make_booking(await make_slot(doctor, TODAY_NOON, minutes=30), athlete)
    web_session(client, registrar)

    early = await client.post(f"{URL}/{appointment_id}/no-show", headers=HX)
    clock.set(msk(2026, 11, 2, 12, 30))
    done = await client.post(f"{URL}/{appointment_id}/no-show", headers=HX)

    assert early.status_code == 409 and "Приём ещё не закончился" in early.text
    assert done.status_code == 200 and 'data-status="no_show"' in row(done.text, f"appt-{appointment_id}")
