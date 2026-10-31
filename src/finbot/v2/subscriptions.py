"""Subscriptions (PRD 6.7): detect repeats, remind before renewals and trial ends."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from ..core.audit import audit
from ..core.ids import new_id
from ..core.ledger import active_expenses
from ..core.lookup import norm
from ..domain.enums import ACTIVE
from ..domain.models import Subscription
from ..domain.money import ZERO


def add(repo, now: datetime, name: str, amount: Decimal, next_renewal: date, **kw) -> Subscription:
    s = repo.add(Subscription(id=new_id("su"), name=name, amount=amount, next_renewal=next_renewal, **kw))
    audit(repo, now, "create", "subscriptions", s.id, name)
    return s


def detect(repo, today: date) -> list[tuple[str, Decimal]]:
    """Same description and amount in two consecutive months, not already tracked."""
    known = {norm(s.name) for s in repo.all(Subscription)}
    seen: dict[tuple[str, Decimal], set[tuple[int, int]]] = defaultdict(set)
    for e in active_expenses(repo):
        if e.description:
            seen[(norm(e.description), e.amount)].add((e.spend_date.year, e.spend_date.month))
    out = []
    for (name, amt), months in seen.items():
        ms = sorted(months)
        if name in known:
            continue
        if any((b[0] * 12 + b[1]) - (a[0] * 12 + a[1]) == 1 for a, b in zip(ms, ms[1:])):
            out.append((name, amt))
    return out


def totals(repo) -> tuple[Decimal, Decimal]:
    subs = repo.find(Subscription, status=ACTIVE)
    monthly = sum((s.amount if s.cycle == "monthly" else s.amount / 12 for s in subs), ZERO)
    return monthly.quantize(Decimal("0.01")), (monthly * 12).quantize(Decimal("0.01"))


def reminders(repo, today: date, lead: int = 3) -> list[tuple[Subscription, str, int]]:
    out = []
    for s in repo.find(Subscription, status=ACTIVE):
        if s.next_renewal and (s.next_renewal - today).days == lead:
            out.append((s, "renewal", lead))
        if s.trial_end and (s.trial_end - today).days == lead:
            out.append((s, "trial_end", lead))
    return out


def renew(repo, s: Subscription) -> Subscription:
    from ..core.items import add_months
    s.next_renewal = add_months(s.next_renewal, 1 if s.cycle == "monthly" else 12)
    repo.update(s)
    return s
