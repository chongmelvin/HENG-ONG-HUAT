from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


class Clock:
    def __init__(self, tz: str = "Asia/Singapore") -> None:
        self.tz = ZoneInfo(tz)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()


class FixedClock(Clock):
    """Deterministic clock for tests."""

    def __init__(self, at: datetime, tz: str = "Asia/Singapore") -> None:
        super().__init__(tz)
        self._at = at.replace(tzinfo=self.tz) if at.tzinfo is None else at

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = at.replace(tzinfo=self.tz) if at.tzinfo is None else at

    def advance(self, **kw) -> None:
        from datetime import timedelta
        self._at += timedelta(**kw)
