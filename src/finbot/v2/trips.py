"""Travel mode (PRD 6.1). Trip spend counts under the Yearly bucket, never Monthly."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from ..core.audit import audit
from ..core.ids import new_id
from ..core.ledger import LedgerError, NetIndex, active_expenses
from ..domain.models import Category, Expense, Settings, Trip
from ..domain.money import ZERO


class TripConflict(LedgerError):
    def __init__(self, active: Trip) -> None:
        super().__init__(f"{active.name} is still on. End or pause it first?")
        self.active = active


def active_trip(repo, settings: Settings) -> Optional[Trip]:
    t = repo.get(Trip, settings.active_trip_id) if settings.active_trip_id else None
    return t if t and t.active and not t.paused else None


def start_trip(repo, settings: Settings, now: datetime, *, name: str, start: date, currency: str,
               end: Optional[date] = None, budget: Optional[Decimal] = None, manual_rate: Optional[Decimal] = None) -> Trip:
    cur = repo.get(Trip, settings.active_trip_id) if settings.active_trip_id else None
    if cur and cur.active and not cur.paused:
        raise TripConflict(cur)
    t = repo.add(Trip(id=new_id("tp"), name=name, start=start, end=end, currency=currency, budget=budget, manual_rate=manual_rate))
    settings.active_trip_id = t.id
    repo.update(settings)
    audit(repo, now, "start", "trips", t.id, name)
    return t


def pause_trip(repo, settings: Settings) -> Trip:
    t = repo.get(Trip, settings.active_trip_id)
    t.paused = True
    repo.update(t)
    settings.active_trip_id = ""
    repo.update(settings)
    return t


def end_trip(repo, settings: Settings, now: datetime) -> Trip:
    t = repo.get(Trip, settings.active_trip_id)
    t.active, t.end = False, t.end or now.date()
    repo.update(t)
    settings.active_trip_id = ""
    repo.update(settings)
    return t


def resume_trip(repo, settings: Settings, trip_id: str) -> Trip:
    t = repo.get(Trip, trip_id)
    t.paused = False
    repo.update(t)
    settings.active_trip_id = t.id
    repo.update(settings)
    return t


def check_state(repo, trip: Trip, today: date) -> Optional[str]:
    """'ended' after a set end date, 'still_on' every 7 days when there is no end date."""
    if trip.end and today > trip.end:
        return "ended"
    if trip.end is None:
        ref = trip.last_check or trip.start
        if (today - ref).days >= 7:
            return "still_on"
    return None


def mark_checked(repo, trip: Trip, today: date) -> None:
    trip.last_check = today
    repo.update(trip)


@dataclass
class TripSummary:
    trip: Trip
    total: Decimal
    by_category: dict[str, Decimal]
    by_day: dict[date, Decimal]
    per_day: Decimal
    budget_used_pct: Optional[float]


def summary(repo, trip_id: str) -> TripSummary:
    trip = repo.get(Trip, trip_id)
    idx = NetIndex(repo)
    cats = {c.id: c.name for c in repo.all(Category)}
    by_cat, by_day = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for e in active_expenses(repo):
        if e.trip_id == trip_id:
            n = idx.net(e)
            by_cat[cats.get(e.category_id, "?")] += n
            by_day[e.spend_date] += n
    total = sum(by_cat.values(), ZERO)
    end = trip.end or (max(by_day) if by_day else trip.start)
    days = max((end - trip.start).days + 1, 1)
    pct = float(total / trip.budget * 100) if trip.budget else None
    return TripSummary(trip, total, dict(by_cat), dict(by_day), (total / days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), pct)
