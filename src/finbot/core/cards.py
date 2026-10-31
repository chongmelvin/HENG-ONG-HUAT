"""Credit cards: statement cycles, utilisation, annual fees, statement mismatches (PRD 5.2)."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ..domain.enums import ACTIVE
from ..domain.models import Card, Settings
from ..domain.money import ZERO
from .ledger import active_expenses
from .networth import computed_balances


def cycle_bounds(card: Card, on: date) -> tuple[date, date]:
    """Cycle runs from the day after one statement day through the next statement day."""
    def stmt(y, m):
        return date(y, m, min(card.statement_day, calendar.monthrange(y, m)[1]))
    this = stmt(on.year, on.month)
    if on <= this:
        end = this
        py, pm = (on.year, on.month - 1) if on.month > 1 else (on.year - 1, 12)
        start = stmt(py, pm) + timedelta(days=1)
    else:
        start = this + timedelta(days=1)
        ny, nm = (on.year, on.month + 1) if on.month < 12 else (on.year + 1, 1)
        end = stmt(ny, nm)
    return start, end


def cycle_spend(repo, card: Card, on: date) -> Decimal:
    s, e = cycle_bounds(card, on)
    t = ZERO
    for ex in active_expenses(repo):
        if s <= ex.spend_date <= e:
            t += sum((p.amount for p in ex.payments if p.account_id == card.account_id), ZERO)
    return t


@dataclass
class CardSummary:
    card: Card
    cycle_start: date
    cycle_end: date
    spent: Decimal
    owed: Decimal
    utilisation_pct: float
    next_due: date


def summarise(repo, settings: Settings, on: date) -> list[CardSummary]:
    bal = computed_balances(repo, settings)
    out = []
    for c in repo.all(Card):
        if c.status != ACTIVE:
            continue
        s, e = cycle_bounds(c, on)
        owed = -bal.get(c.account_id, ZERO)
        util = float(owed / c.limit * 100) if c.limit else 0.0
        due_m = e.month + (1 if c.due_day <= c.statement_day else 0)
        due_y = e.year + (1 if due_m > 12 else 0)
        due_m = 1 if due_m > 12 else due_m
        due = date(due_y, due_m, min(c.due_day, calendar.monthrange(due_y, due_m)[1]))
        out.append(CardSummary(c, s, e, cycle_spend(repo, c, on), owed, util, due))
    return out


def statement_gap(repo, card: Card, statement_total: Decimal, on: date) -> Decimal:
    """Positive = the statement is higher than what you logged (entries are missing)."""
    return statement_total - cycle_spend(repo, card, on)


def annual_fee_due(repo, today: date) -> list[Card]:
    return [c for c in repo.all(Card) if c.status == ACTIVE and c.annual_fee > 0 and c.fee_month == today.month and today.day == 1]
