"""Slot time rules: what a new slot (or a batch) may look like. Pure, no I/O; "now" comes from the injected clock."""

from datetime import UTC, datetime, timedelta

from app.core.clock import Clock
from app.core.config import Settings
from app.core.exceptions import InvalidInput

OUT_OF_RANGE = "Time is out of the supported range"
SECONDS_NOT_ZERO = "Slot times must have zero seconds"
END_NOT_AFTER_START = "end_at must be later than start_at"
SLOT_IN_PAST = "Slot must start in the future"
BEYOND_HORIZON = "Slot is beyond the schedule horizon"
WINDOW_TOO_LONG = "Window is longer than 12 hours"
WINDOW_NOT_DIVISIBLE = "Window is not divisible by slot_minutes"

type Interval = tuple[datetime, datetime]


class SlotPlanner:
    def __init__(self, settings: Settings, clock: Clock) -> None:
        self.settings = settings
        self.clock = clock

    def single(self, start_at: datetime, end_at: datetime) -> Interval:
        start, end = self._normalized(start_at, end_at)
        minutes = (end - start) / timedelta(minutes=1)
        self._check_length(minutes)
        self._check_start(start)
        return start, end

    def batch(self, start_at: datetime, end_at: datetime, slot_minutes: int) -> list[Interval]:
        start, end = self._normalized(start_at, end_at)
        self._check_length(slot_minutes)
        window = end - start
        if window > timedelta(hours=self.settings.batch_max_window_hours):
            raise InvalidInput(WINDOW_TOO_LONG)
        step = timedelta(minutes=slot_minutes)
        if window % step:
            raise InvalidInput(WINDOW_NOT_DIVISIBLE)
        count = window // step
        if count > self.settings.batch_max_slots:
            raise InvalidInput(f"Too many slots in the batch (max {self.settings.batch_max_slots})")
        intervals = [(start + step * i, start + step * (i + 1)) for i in range(count)]
        self._check_start(intervals[0][0])
        self._check_start(intervals[-1][0])
        return intervals

    def _normalized(self, start_at: datetime, end_at: datetime) -> Interval:
        try:
            start, end = start_at.astimezone(UTC), end_at.astimezone(UTC)
        except OverflowError:  # e.g. 9999-12-31T23:59:00-05:00 does not fit into UTC
            raise InvalidInput(OUT_OF_RANGE) from None
        if any(t.second or t.microsecond for t in (start, end)):
            raise InvalidInput(SECONDS_NOT_ZERO)
        if end <= start:
            raise InvalidInput(END_NOT_AFTER_START)
        return start, end

    def _check_length(self, minutes: float) -> None:
        low, high = self.settings.slot_min_minutes, self.settings.slot_max_minutes
        if not low <= minutes <= high:
            raise InvalidInput(f"Slot length must be between {low} and {high} minutes")

    def _check_start(self, start: datetime) -> None:
        now = self.clock.now()
        if start <= now:
            raise InvalidInput(SLOT_IN_PAST)
        if start > now + timedelta(days=self.settings.schedule_horizon_days):
            raise InvalidInput(BEYOND_HORIZON)
