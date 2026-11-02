"""Demo slots and appointments (stage 2.1, spec 5.3-5.5). Written through repositories and `StatusChanger`.

The services are not used on purpose: they refuse past slots and check roles. The data still follows the same
rules (slot/appointment transitions with the proper actor, status_history, audit, DB constraints, athlete limits),
and the result must satisfy `assert_schedule_invariants`. Callers own the transactions of the blocks.
"""

import random
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.audit.service import AuditService
from app.core.clock import Clock
from app.core.config import Settings
from app.core.local_time import LocalCalendar
from app.core.rbac import Role
from app.core.uow import UnitOfWork
from app.models.enums import AppointmentStatus, SlotStatus
from app.models.schedule import Appointment, Slot
from app.repositories.schedule import AppointmentRepository, SlotRepository
from app.services.status import APPOINTMENT_TRANSITIONS, SLOT_TRANSITIONS, StatusChanger

RNG_SEED = 20261031
DAYS_BACK = 14
DAYS_AHEAD = 14
SLOT_MINUTES = 30
WORK_WINDOWS = ((time(9, 0), time(12, 0)), (time(14, 0), time(17, 0)))  # Moscow wall clock
CLOSED_EVERY = 5  # every 5th future slot is closed

PAST, TODAY, FUTURE = "past", "today", "future"
B, A, D, N, C = (
    AppointmentStatus.BOOKED,
    AppointmentStatus.ARRIVED,
    AppointmentStatus.DONE,
    AppointmentStatus.NO_SHOW,
    AppointmentStatus.CANCELLED,
)
# (period, final status, count): above the minimums of the spec 5.4 by a few rows.
APPOINTMENT_PLAN = (
    (PAST, D, 10),
    (PAST, N, 5),
    (PAST, C, 5),
    (TODAY, A, 3),
    (TODAY, B, 3),
    (FUTURE, B, 18),
    (FUTURE, C, 4),
)


@dataclass(frozen=True, slots=True)
class DemoActors:
    admin_id: int
    registrar_id: int
    doctor_ids: list[int]
    athlete_ids: list[int]


class DemoSlots:
    """Slot grid of every doctor for [today - 14, today + 14] in the local zone; idempotent by (doctor, start)."""

    def __init__(
        self,
        uow: UnitOfWork,
        slots: SlotRepository,
        status: StatusChanger,
        audit: AuditService,
        clock: Clock,
        calendar: LocalCalendar,
    ) -> None:
        self.uow = uow
        self.slots = slots
        self.status = status
        self.audit = audit
        self.clock = clock
        self.calendar = calendar

    async def ensure(self, admin_id: int, doctor_ids: list[int]) -> int:
        """Returns the number of created slots; one transaction per doctor."""
        today = self.calendar.day_of(self.clock.now())
        grid = self._grid(today)
        created = 0
        for position, doctor_id in enumerate(doctor_ids):
            existing = {s.start_at for s in await self.slots.overlapping(doctor_id, grid[0][0], grid[-1][1])}
            new = [cell for cell in grid if cell[0] not in existing]
            slots = [
                Slot(doctor_id=doctor_id, start_at=s, end_at=e, status=SlotStatus.FREE, created_by=admin_id)
                for s, e, _, _ in new
            ]
            await self.slots.add_many(slots)
            for slot, (_, _, day, index) in zip(slots, new, strict=True):
                await self.audit.log(user_id=admin_id, action="slot_create", entity_type="slot", entity_id=slot.id)
                if day > today and (day.toordinal() * 12 + index + position) % CLOSED_EVERY == CLOSED_EVERY - 1:
                    await self._close(slot, admin_id)
            await self.uow.commit()
            created += len(slots)
        return created

    async def _close(self, slot: Slot, admin_id: int) -> None:
        slot.updated_by = admin_id
        await self.status.change(
            slot,
            entity_type="slot",
            to_status=SlotStatus.CLOSED,
            transitions=SLOT_TRANSITIONS,
            actor=Role.ADMIN,
            actor_id=admin_id,
        )
        await self.audit.log(user_id=admin_id, action="slot_close", entity_type="slot", entity_id=slot.id)

    def _grid(self, today: date) -> list[tuple[datetime, datetime, date, int]]:
        """All (start, end, local day, index within the day) cells of the window, chronologically."""
        cells = []
        for offset in range(-DAYS_BACK, DAYS_AHEAD + 1):
            day = today + timedelta(days=offset)
            index = 0
            for begin, finish in WORK_WINDOWS:
                moment = datetime.combine(day, begin)
                while moment.time() < finish:
                    nxt = moment + timedelta(minutes=SLOT_MINUTES)
                    cells.append((self.calendar.at(day, moment.time()), self.calendar.at(day, nxt.time()), day, index))
                    index += 1
                    moment = nxt
        return cells


class DemoAppointments:
    """Appointments in every status, in the past, today and the future. Skipped when the athletes have any."""

    def __init__(
        self,
        uow: UnitOfWork,
        slots: SlotRepository,
        appointments: AppointmentRepository,
        status: StatusChanger,
        audit: AuditService,
        clock: Clock,
        calendar: LocalCalendar,
        settings: Settings,
    ) -> None:
        self.uow = uow
        self.slots = slots
        self.appointments = appointments
        self.status = status
        self.audit = audit
        self.clock = clock
        self.calendar = calendar
        self.settings = settings

    async def ensure(self, actors: DemoActors) -> Counter[str]:
        """Returns the created appointments counted by final status (empty when nothing was created)."""
        if await self.appointments.exists_for_athletes(actors.athlete_ids):
            return Counter()
        now = self.clock.now()
        today = self.calendar.day_of(now)
        window = (
            self.calendar.day_start(today - timedelta(days=DAYS_BACK)),
            self.calendar.day_start(today + timedelta(days=DAYS_AHEAD + 1)),
        )
        pools = self._pools(await self.slots.free_between(*window), today)
        rng = random.Random(RNG_SEED)  # noqa: S311 (demo data, not security)
        chosen = [
            (slot, final) for period, final, count in APPOINTMENT_PLAN for slot in self._pick(rng, pools[period], count)
        ]
        athletes = _AthletePicker(actors.athlete_ids, rng, self.settings.max_active_appointments)
        created: Counter[str] = Counter()
        for slot, final in chosen:
            athlete_id = athletes.next_for(slot, final)
            await self._create(slot, athlete_id, final, actors, now)
            created[final.value] += 1
        await self.uow.commit()
        return created

    def _pools(self, free_slots: list[Slot], today: date) -> dict[str, list[Slot]]:
        pools: dict[str, list[Slot]] = {PAST: [], TODAY: [], FUTURE: []}
        for slot in free_slots:
            day = self.calendar.day_of(slot.start_at)
            pools[PAST if day < today else TODAY if day == today else FUTURE].append(slot)
        return pools

    @staticmethod
    def _pick(rng: random.Random, pool: list[Slot], count: int) -> list[Slot]:
        """A random sample without repeats; taken slots leave the pool so that categories never share a slot."""
        if count > len(pool):
            raise RuntimeError(f"Demo seed needs {count} free slots in a period but only {len(pool)} are left")
        picked = rng.sample(pool, count)
        for slot in picked:
            pool.remove(slot)
        return picked

    async def _create(
        self, slot: Slot, athlete_id: int, final: AppointmentStatus, actors: DemoActors, now: datetime
    ) -> None:
        appointment = Appointment(
            slot_id=slot.id,
            athlete_id=athlete_id,
            case_id=None,
            status=B,
            created_by=athlete_id,
            updated_by=athlete_id,
        )
        await self.appointments.add(appointment)
        await self.status.created(entity_type="appointment", entity_id=appointment.id, status=B, actor_id=athlete_id)
        await self._move_slot(slot, SlotStatus.BOOKED, athlete_id)
        await self._audit("appointment_book", appointment, athlete_id)

        if final in (A, D):
            await self._set(appointment, A, Role.REGISTRAR, actors.registrar_id)
            await self._audit("appointment_arrive", appointment, actors.registrar_id)
        if final is D:
            await self._set(appointment, D, Role.DOCTOR, slot.doctor_id)
        if final is N:
            await self._set(appointment, N, Role.REGISTRAR, actors.registrar_id)
            await self._audit("appointment_no_show", appointment, actors.registrar_id)
        if final is C:
            appointment.cancelled_at = min(now, slot.start_at - timedelta(days=1))
            await self._set(appointment, C, Role.ATHLETE, athlete_id)
            await self._move_slot(slot, SlotStatus.FREE, athlete_id)
            await self._audit("appointment_cancel", appointment, athlete_id)

    async def _set(self, appointment: Appointment, to: AppointmentStatus, role: Role, actor_id: int) -> None:
        appointment.updated_by = actor_id
        await self.status.change(
            appointment,
            entity_type="appointment",
            to_status=to,
            transitions=APPOINTMENT_TRANSITIONS,
            actor=role,
            actor_id=actor_id,
        )

    async def _move_slot(self, slot: Slot, to: SlotStatus, athlete_id: int) -> None:
        slot.updated_by = athlete_id
        await self.status.change(
            slot,
            entity_type="slot",
            to_status=to,
            transitions=SLOT_TRANSITIONS,
            actor=Role.ATHLETE,
            actor_id=athlete_id,
        )

    async def _audit(self, action: str, appointment: Appointment, actor_id: int) -> None:
        await self.audit.log(user_id=actor_id, action=action, entity_type="appointment", entity_id=appointment.id)


class _AthletePicker:
    """Round-robin over a shuffled athlete list; skips athletes whose active appointments overlap or hit the limit."""

    def __init__(self, athlete_ids: list[int], rng: random.Random, max_active: int) -> None:
        self.order = list(athlete_ids)
        rng.shuffle(self.order)
        self.max_active = max_active
        self.cursor = 0
        self.active: dict[int, list[tuple[datetime, datetime]]] = {a: [] for a in athlete_ids}

    def next_for(self, slot: Slot, final: AppointmentStatus) -> int:
        counts_as_active = final in (B, A)
        for _ in range(len(self.order)):
            athlete_id = self.order[self.cursor % len(self.order)]
            self.cursor += 1
            busy = self.active[athlete_id]
            if not counts_as_active or (
                len(busy) < self.max_active and not any(s < slot.end_at and e > slot.start_at for s, e in busy)
            ):
                if counts_as_active:
                    busy.append((slot.start_at, slot.end_at))
                return athlete_id
        raise RuntimeError("No athlete can take the demo appointment")
