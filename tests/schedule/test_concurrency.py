"""Spec section 11: races on the schedule, real PostgreSQL, one session per request, common timeout.

Every test ends with assert_schedule_invariants (autouse fixture of this package).
"""

import random
from datetime import timedelta

from app.core.rbac import Role
from tests.schedule.support import (
    arrive,
    at,
    book,
    cancel,
    close_slot,
    gather,
    no_show,
    post_slot,
    reopen_slot,
)

NO_5XX = "no request may end with a server error"


def codes(responses) -> list[int]:
    return [r.status_code for r in responses]


async def active_appointments(sql, slot_id: int | None = None) -> list[dict]:
    query = "SELECT id, slot_id, athlete_id, status FROM appointments WHERE status <> 'cancelled'"
    if slot_id is not None:
        return await sql(query + " AND slot_id = :s ORDER BY id", s=slot_id)
    return await sql(query + " ORDER BY id")


async def test_parallel_bookings_of_one_slot_create_exactly_one_appointment(
    client, clock, make_user, doctor, make_slot, sql, audit
):
    athletes = [await make_user(Role.ATHLETE, last_name=f"Атлет{n}") for n in range(20)]
    slot_id = await make_slot(doctor, at(10))

    resps = await gather(*(book(client, a, slot_id) for a in athletes))

    assert sorted(codes(resps)) == [201] + [409] * 19, codes(resps)
    assert {r.json()["detail"] for r in resps if r.status_code == 409} == {"Slot is already taken"}
    winner = next(r for r in resps if r.status_code == 201).json()
    [active] = await active_appointments(sql, slot_id)
    assert active["id"] == winner["id"] and active["athlete_id"] == winner["athlete_id"]
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "booked"
    assert len(await audit("appointment_book")) == 1
    assert len(await sql("SELECT id FROM appointments")) == 1


async def test_booking_race_between_athlete_and_registrar(client, clock, registrar, athlete, doctor, make_slot, sql):
    for n in range(5):
        slot_id = await make_slot(doctor, at(8 + n))

        by_athlete, by_registrar = await gather(
            book(client, athlete, slot_id), book(client, registrar, slot_id, athlete)
        )

        assert sorted([by_athlete.status_code, by_registrar.status_code]) == [201, 409]
        assert len(await active_appointments(sql, slot_id)) == 1
        # the athlete may not hold two overlapping appointments, so the duplicate is rejected whichever reason fires
        loser = by_athlete if by_athlete.status_code == 409 else by_registrar
        assert loser.json()["detail"] in ("Slot is already taken", "Athlete has an overlapping appointment")


async def test_many_athletes_many_slots_every_slot_gets_at_most_one_appointment(
    client, clock, make_user, doctor, make_slot, sql
):
    athletes = [await make_user(Role.ATHLETE, last_name=f"Атлет{n}") for n in range(30)]
    slots = [await make_slot(doctor, at(8) + timedelta(minutes=30 * i)) for i in range(10)]
    rng = random.Random(20261102)

    async def one_athlete(athlete):
        order = rng.sample(slots, len(slots))
        out = []
        for slot_id in order:
            out.append(await book(client, athlete, slot_id))
        return out

    results = await gather(*(one_athlete(a) for a in athletes), timeout=120)

    flat = [r for per_athlete in results for r in per_athlete]
    assert all(r.status_code in (201, 409) for r in flat), NO_5XX
    created = [r for r in flat if r.status_code == 201]
    assert len(created) == 10  # every slot ends up taken, each exactly once
    per_slot = await sql("SELECT slot_id, count(*) AS n FROM appointments WHERE status <> 'cancelled' GROUP BY slot_id")
    assert {r["slot_id"]: r["n"] for r in per_slot} == dict.fromkeys(slots, 1)
    assert {r["status"] for r in await sql("SELECT status FROM slots")} == {"booked"}


async def test_parallel_bookings_of_overlapping_slots_by_one_athlete_succeed_once(
    client, clock, registrar, athlete, doctor, doctor2, make_slot, sql
):
    for n in range(4):
        first = await make_slot(doctor, at(8 + 2 * n))
        second = await make_slot(doctor2, at(8 + 2 * n, 15))

        resps = await gather(book(client, athlete, first), book(client, registrar, second, athlete))

        assert sorted(codes(resps)) == [201, 409], [r.text for r in resps]
        assert (
            next(r for r in resps if r.status_code == 409).json()["detail"] == "Athlete has an overlapping appointment"
        )


async def test_parallel_bookings_cannot_exceed_the_active_limit(
    client, clock, settings_env, athlete, doctor, make_slot, sql
):
    settings_env(max_active_appointments=3)
    slots = [await make_slot(doctor, at(8) + timedelta(minutes=30 * i)) for i in range(8)]

    resps = await gather(*(book(client, athlete, s) for s in slots))

    assert sorted(codes(resps)) == [201] * 3 + [409] * 5, codes(resps)
    assert {r.json()["detail"] for r in resps if r.status_code == 409} == {"Too many active appointments"}
    assert len(await active_appointments(sql)) == 3


async def test_parallel_double_cancel_is_idempotent_and_audited_once(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, sql, audit
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)

    resps = await gather(
        cancel(client, athlete, appointment_id),
        cancel(client, registrar, appointment_id),
        cancel(client, athlete, appointment_id),
        cancel(client, registrar, appointment_id),
    )

    assert codes(resps) == [204] * 4
    assert len(await audit("appointment_cancel")) == 1
    history = await sql("SELECT id FROM status_history WHERE entity_type = 'appointment' AND to_status = 'cancelled'")
    assert len(history) == 1
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "free"


async def test_cancel_and_booking_race_leaves_consistent_state(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking, sql
):
    for n in range(6):
        slot_id = await make_slot(doctor, at(8 + n))
        first = await make_booking(slot_id, athlete)

        cancelled, booked = await gather(cancel(client, athlete, first), book(client, athlete2, slot_id))

        assert cancelled.status_code == 204
        assert booked.status_code in (201, 409), booked.text
        active = await active_appointments(sql, slot_id)
        if booked.status_code == 201:
            assert [a["athlete_id"] for a in active] == [athlete2.id]
            assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == "booked"
        else:
            assert booked.json()["detail"] == "Slot is already taken" and active == []
            assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == "free"


async def test_cancel_rebook_cycles_in_parallel_keep_one_active_appointment(
    client, clock, make_user, doctor, make_slot, sql
):
    athletes = [await make_user(Role.ATHLETE, last_name=f"Атлет{n}") for n in range(3)]
    slot_id = await make_slot(doctor, at(10))

    async def cycle(athlete):
        out = []
        for _ in range(3):
            resp = await book(client, athlete, slot_id)
            out.append(resp)
            if resp.status_code == 201:
                out.append(await cancel(client, athlete, resp.json()["id"]))
        return out

    results = await gather(*(cycle(a) for a in athletes))

    flat = [r for per in results for r in per]
    assert all(r.status_code in (201, 204, 409) for r in flat), codes(flat)
    assert len(await active_appointments(sql, slot_id)) <= 1
    expected_slot = "booked" if await active_appointments(sql, slot_id) else "free"
    assert (await sql("SELECT status FROM slots"))[0]["status"] == expected_slot


async def test_close_and_booking_race_never_closes_a_booked_slot(client, clock, doctor, athlete, make_slot, sql):
    for n in range(6):
        slot_id = await make_slot(doctor, at(8 + n))

        closed, booked = await gather(close_slot(client, doctor, slot_id), book(client, athlete, slot_id))

        if closed.status_code == 204:
            assert booked.status_code == 409 and booked.json()["detail"] == "Slot is closed"
            assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == "closed"
        else:
            assert closed.status_code == 409 and closed.json()["detail"] == "Slot is booked"
            assert booked.status_code == 201
            assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == "booked"


async def test_reopen_and_booking_race(client, clock, doctor, athlete, make_slot, sql):
    for n in range(4):
        slot_id = await make_slot(doctor, at(8 + n), status="closed")

        reopened, booked = await gather(reopen_slot(client, doctor, slot_id), book(client, athlete, slot_id))

        assert reopened.status_code == 204
        assert booked.status_code in (201, 409)
        expected = "booked" if booked.status_code == 201 else "free"
        assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == expected


async def test_parallel_creation_of_overlapping_slots_creates_one(client, clock, doctor, admin, sql):
    attempts = [
        post_slot(client, doctor, at(10)),
        post_slot(client, doctor, at(10)),
        post_slot(client, doctor, at(10, 10), minutes=30),
        post_slot(client, admin, at(10, 20), minutes=30, doctor=doctor),
        post_slot(client, doctor, at(9, 45), minutes=30),
    ]

    resps = await gather(*attempts)

    assert sorted(codes(resps)) == [201, 409, 409, 409, 409], [r.text for r in resps]
    assert all(r.json()["detail"].startswith("Slots overlap") for r in resps if r.status_code == 409)
    assert len(await sql("SELECT id FROM slots")) == 1


async def test_parallel_creation_of_touching_slots_succeeds_for_all(client, clock, doctor, sql):
    resps = await gather(*(post_slot(client, doctor, at(8) + timedelta(minutes=30 * i)) for i in range(8)))

    assert codes(resps) == [201] * 8
    assert len(await sql("SELECT id FROM slots")) == 8


async def test_mixed_workload_does_not_deadlock(
    client, clock, admin, registrar, doctor, doctor2, make_user, make_slot, insert_booking, sql
):
    """100 operations of every kind on a shared set of slots, in random order, 30 s for all of them."""
    athletes = [await make_user(Role.ATHLETE, last_name=f"Атлет{n}") for n in range(6)]
    # slots today (arrival is possible) and tomorrow; 12 per doctor, no overlaps inside one doctor
    today = [await make_slot(doctor, at(12, days=0) + timedelta(minutes=30 * i)) for i in range(6)]
    tomorrow = [await make_slot(doctor2, at(8) + timedelta(minutes=30 * i)) for i in range(6)]
    pre_booked = {}
    for i, slot_id in enumerate(today[:3] + tomorrow[:3]):
        pre_booked[slot_id] = await insert_booking(slot_id, athletes[i])
    rng = random.Random(7)
    pool = today + tomorrow
    appointments = list(pre_booked.values())

    def operation(n: int):
        kind = rng.choice(["book", "book", "cancel", "arrive", "close", "reopen", "create", "no_show"])
        slot_id = rng.choice(pool)
        athlete = rng.choice(athletes)
        if kind == "book":
            return book(client, rng.choice([athlete, registrar, admin]), slot_id, athlete)
        if kind == "cancel":
            return cancel(client, rng.choice([registrar, admin]), rng.choice(appointments))
        if kind == "arrive":
            return arrive(client, registrar, rng.choice(appointments))
        if kind == "close":
            return close_slot(client, rng.choice([doctor, doctor2, admin]), slot_id)
        if kind == "reopen":
            return reopen_slot(client, rng.choice([doctor, doctor2, admin]), slot_id)
        if kind == "no_show":
            return no_show(client, registrar, rng.choice(appointments))
        return post_slot(client, doctor, at(14, days=2) + timedelta(minutes=10 * n), minutes=10)

    resps = await gather(*(operation(n) for n in range(100)), timeout=30)

    assert all(r.status_code < 500 for r in resps), [(r.status_code, r.text) for r in resps if r.status_code >= 500]
    assert all(r.status_code in (200, 201, 204, 403, 404, 409, 422) for r in resps), sorted(set(codes(resps)))
    assert (
        len(
            await sql(
                "SELECT slot_id FROM appointments WHERE status <> 'cancelled' GROUP BY slot_id HAVING count(*) > 1"
            )
        )
        == 0
    )


async def test_booking_the_same_free_slot_for_two_different_athletes_by_staff_in_parallel(
    client, clock, registrar, admin, athlete, athlete2, doctor, make_slot, sql
):
    slot_id = await make_slot(doctor, at(10))

    resps = await gather(book(client, registrar, slot_id, athlete), book(client, admin, slot_id, athlete2))

    assert sorted(codes(resps)) == [201, 409]
    assert len(await active_appointments(sql, slot_id)) == 1


async def test_deactivation_of_the_athlete_during_booking_never_leaves_a_half_made_booking(
    client, clock, admin, make_user, doctor, make_slot, sql
):
    for n in range(4):
        victim = await make_user(Role.ATHLETE, last_name=f"Жертва{n}")
        slot_id = await make_slot(doctor, at(8 + n))

        booking, deactivation = await gather(
            book(client, admin, slot_id, victim), client.post(f"/users/{victim.id}/deactivate", headers=admin.headers)
        )

        assert deactivation.status_code == 204
        assert booking.status_code in (201, 422), booking.text  # booked before the deactivation, or rejected after it
        expected = "booked" if booking.status_code == 201 else "free"
        assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == expected
