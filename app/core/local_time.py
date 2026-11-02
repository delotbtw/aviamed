"""Moscow <-> UTC and "calendar day in the configured zone" in one place (spec 7.1).

The database and services work with aware UTC datetimes; this class translates to and from the local calendar
(`settings.schedule_timezone`). Pages and JSON filters use it, nobody hardcodes an offset.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


class LocalCalendar:
    def __init__(self, timezone: str) -> None:
        self.tz = ZoneInfo(timezone)

    def to_local(self, moment: datetime) -> datetime:
        return moment.astimezone(self.tz)

    def day_of(self, moment: datetime) -> date:
        return moment.astimezone(self.tz).date()

    def at(self, day: date, at: time = time.min) -> datetime:
        """Local wall-clock time -> aware UTC.

        Zones with DST are not handled: a non-existent local time is shifted forward and an ambiguous one takes the
        first occurrence (fold=0). Europe/Moscow has neither (spec 7.1); revisit before switching to such a zone.
        """
        return datetime.combine(day, at, tzinfo=self.tz).astimezone(UTC)

    def day_start(self, day: date) -> datetime:
        return self.at(day)

    def next_day_start(self, day: date) -> datetime:
        return self.at(day + timedelta(days=1))
