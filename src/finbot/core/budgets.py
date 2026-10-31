"""Budgets, budget-left lines, pace and the first-breach 'scold' rules (PRD 4.3, 4.6)."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from ..domain.enums import ACTIVE, Bucket
from ..domain.models import BudgetLimit, Category, Expense, Receivable, Settings
from ..domain.money import ZERO
from .audit import audit
from .ids import new_id
from .indicators import budget_light, pace_light
from .ledger import NetIndex, active_expenses

TOTAL_M, TOTAL_Y = "total_monthly", "total_yearly"


def month_bounds(y: int, m: int) -> tuple[date, date]:
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def year_bounds(y: int) -> tuple[date, date]:
    return date(y, 1, 1), date(y, 12, 31)


def limit_in_force(repo, scope: str, on: date) -> Optional[Decimal]:
    """Limits keep effective dates so past periods are judged against the limit in force then."""
    ls = [l for l in repo.find(BudgetLimit, scope=scope) if l.effective_from <= on]
    return max(ls, key=lambda l: (l.effective_from, l.id)).amount if ls else None


def set_limit(repo, now, scope: str, amount: Decimal, effective_from: Optional[date] = None) -> BudgetLimit:
    eff = effective_from or date(now.year, now.month, 1)
    existing = [l for l in repo.find(BudgetLimit, scope=scope) if l.effective_from == eff]
    if existing:
        existing[0].amount = amount
        repo.update(existing[0])
        lim = existing[0]
    else:
        lim = repo.add(BudgetLimit(id=new_id("bl"), scope=scope, amount=amount, effective_from=eff))
    audit(repo, now, "set_limit", "limits", lim.id, f"{scope}={amount}")
    return lim


def category_limit_sum(repo, on: date) -> Decimal:
    total = ZERO
    for c in repo.all(Category):
        if c.status == ACTIVE and c.default_bucket == Bucket.MONTHLY:
            total += limit_in_force(repo, f"category:{c.id}", on) or ZERO
    return total


def spent(idx: NetIndex, exps: list[Expense], start: date, end: date, *,
          bucket: Optional[Bucket] = None, category_id: Optional[str] = None) -> Decimal:
    t = ZERO
    for e in exps:
        if start <= e.spend_date <= end and (bucket is None or e.bucket == bucket) \
                and (category_id is None or e.category_id == category_id):
            t += idx.net(e)
    return t


@dataclass
class Line:
    label: str
    spent: Decimal
    limit: Decimal
    light: str

    @property
    def left(self) -> Decimal:
        return self.limit - self.spent

    @property
    def used_pct(self) -> float:
        return float(self.spent / self.limit * 100) if self.limit else 0.0


def _line(label, sp, lim) -> Line:
    return Line(label, sp, lim, budget_light(float(sp / lim * 100)) if lim else "")


def lines_for(repo, exp: Expense, *, include_exp: bool = True) -> list[Line]:
    """The budget-left lines shown under a saved entry."""
    idx, exps = NetIndex(repo), active_expenses(repo)
    if not include_exp:
        exps = [e for e in exps if e.id != exp.id]
    on = exp.spend_date
    out: list[Line] = []
    cat = repo.get(Category, exp.category_id)
    if exp.bucket == Bucket.MONTHLY:
        s, e = month_bounds(on.year, on.month)
        tl = limit_in_force(repo, TOTAL_M, on)
        if tl:
            out.append(_line("Monthly budget", spent(idx, exps, s, e, bucket=Bucket.MONTHLY), tl))
        cl = limit_in_force(repo, f"category:{exp.category_id}", on)
        if cl and cat:
            out.append(_line(cat.name, spent(idx, exps, s, e, bucket=Bucket.MONTHLY, category_id=exp.category_id), cl))
    else:
        s, e = year_bounds(on.year)
        yl = limit_in_force(repo, TOTAL_Y, on)
        if yl:
            out.append(_line("Yearly bucket", spent(idx, exps, s, e, bucket=Bucket.YEARLY), yl))
    return out


def yearly_pace(repo, today: date) -> Optional[tuple[float, float, str]]:
    """(spent fraction, elapsed fraction, light) for the Yearly bucket."""
    yl = limit_in_force(repo, TOTAL_Y, today)
    if not yl:
        return None
    idx, exps = NetIndex(repo), active_expenses(repo)
    s, e = year_bounds(today.year)
    sp = float(spent(idx, exps, s, e, bucket=Bucket.YEARLY) / yl)
    elapsed = (today - s).days / ((e - s).days + 1)
    return sp, elapsed, pace_light(sp, elapsed)


def monthly_pace(repo, today: date) -> Optional[tuple[float, float, str]]:
    tl = limit_in_force(repo, TOTAL_M, today)
    if not tl:
        return None
    idx, exps = NetIndex(repo), active_expenses(repo)
    s, e = month_bounds(today.year, today.month)
    sp = float(spent(idx, exps, s, e, bucket=Bucket.MONTHLY) / tl)
    elapsed = today.day / e.day
    return sp, elapsed, pace_light(sp, elapsed)


# --------------------------------------------------------------------- scolding
@dataclass
class Breach:
    kind: str                  # first | still | firm
    label: str
    over_by: Decimal
    months_in_row: int = 1


def check_breach(repo, settings: Settings, exp: Expense) -> Optional[Breach]:
    """First breach in the month -> 'first' (scold). Later entries -> 'still' (plain). 3 months running -> 'firm'.

    Never scolds for exempt categories, claimable items, entries expecting repayment, backdated
    entries, or trip spend.
    """
    cat = repo.get(Category, exp.category_id)
    if exp.bucket != Bucket.MONTHLY or exp.spend_date != exp.entry_date:
        return None
    if cat is None or cat.exempt_scold or exp.claimable or exp.trip_id:
        return None
    if repo.find(Receivable, expense_id=exp.id):
        return None
    on = exp.spend_date
    idx, exps = NetIndex(repo), active_expenses(repo)
    s, e = month_bounds(on.year, on.month)
    for scope, label, cid in ((f"category:{cat.id}", cat.name, cat.id), (TOTAL_M, "Monthly budget", None)):
        lim = limit_in_force(repo, scope, on)
        if not lim:
            continue
        after = spent(idx, exps, s, e, bucket=Bucket.MONTHLY, category_id=cid)
        before = after - idx.net(exp)
        if after > lim:
            over = after - lim
            if before <= lim:
                return Breach("firm" if _months_over(repo, idx, exps, cid, scope, on) >= 3 else "first", label, over,
                              _months_over(repo, idx, exps, cid, scope, on))
            return Breach("still", label, over)
    return None


def _months_over(repo, idx, exps, cid, scope, on: date) -> int:
    n, y, m = 1, on.year, on.month
    for _ in range(11):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        s, e = month_bounds(y, m)
        lim = limit_in_force(repo, scope, s)
        if not lim or spent(idx, exps, s, e, bucket=Bucket.MONTHLY, category_id=cid) <= lim:
            break
        n += 1
    return n
