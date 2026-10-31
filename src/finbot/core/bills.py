"""Bills, premiums and subscriptions that need a reminder (PRD 4.5, 5.2)."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from ..domain.enums import ACTIVE, Bucket
from ..domain.models import Account, Bill, Payment
from ..domain.money import ZERO
from .audit import audit
from .ids import new_id
from .indicators import bill_light
from .ledger import ExpenseInput, ExpenseResult, LedgerError, create_expense, create_transfer

STEP = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}


def clamp_day(y: int, m: int, day: int) -> date:
    """A bill on the 31st falls on the last day of shorter months."""
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def occurrences(bill: Bill, start: date, end: date) -> list[date]:
    step = STEP[bill.recurrence]
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        if (m - bill.anchor_month) % step == 0:
            d = clamp_day(y, m, bill.due_day)
            if start <= d <= end:
                out.append(d)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def next_due(bill: Bill, today: date) -> date:
    """Next unpaid due date. Past dates after the last payment count as overdue.

    A bill that has never been paid starts counting from the day it was created, so a new bill
    is never instantly overdue for months that passed before it existed.
    """
    start = bill.last_paid + timedelta(days=1) if bill.last_paid else (bill.created or today)
    occ = occurrences(bill, start, today + timedelta(days=400))
    return occ[0] if occ else today


def due_today(repo, today: date) -> list[tuple[Bill, date, int, str]]:
    """Reminders to send now: due in `lead_days`, due today, or overdue. [(bill, due, days_to_due, light)]"""
    out = []
    for b in repo.find(Bill, status=ACTIVE):
        if b.snooze_until and b.snooze_until > today:
            continue
        d = next_due(b, today)
        delta = (d - today).days
        if delta == b.lead_days or delta <= 0:
            out.append((b, d, delta, bill_light(delta)))
    return out


def create_bill(repo, now, **kw) -> Bill:
    day = kw.get("due_day", 1)
    if not 1 <= int(day) <= 31:
        raise LedgerError("A day must be 1 to 31. (31 means the last day of shorter months.)")
    b = Bill(id=new_id("bi"), created=now.date(), **kw)
    repo.add(b)
    audit(repo, now, "create", "bills", b.id, b.name)
    return b


def snooze(repo, bill_id: str, today: date, days: int = 1) -> Bill:
    b = repo.get(Bill, bill_id)
    b.snooze_until = today + timedelta(days=days)
    repo.update(b)
    return b


def skip(repo, bill_id: str, today: date) -> Bill:
    b = repo.get(Bill, bill_id)
    b.last_paid = next_due(b, today)
    repo.update(b)
    return b


def mark_paid(repo, settings, now: datetime, bill_id: str, amount: Decimal) -> ExpenseResult | None:
    """Paid: bills become an expense; card payments become a transfer (PRD 4.5)."""
    b = repo.get(Bill, bill_id)
    if amount <= 0:
        raise LedgerError("I need a number, for example 40.00.")
    if b.paid_on == now.date():
        raise LedgerError("Already logged.")
    res = None
    if b.is_transfer:
        create_transfer(repo, now, from_account=b.account_id, to_account=b.ref_id, amount=amount, on=now.date(),
                        note=f"{b.name} payment")
    else:
        cat = b.category_id
        bucket = Bucket.YEARLY if b.recurrence in ("yearly", "half_yearly") and b.kind == "insurance" else Bucket.MONTHLY
        res = create_expense(repo, settings, ExpenseInput(
            amount=amount, category_id=cat, bucket=bucket, payments=[Payment(b.account_id, amount)],
            spend_date=now.date(), description=b.name, tags=["Recurring"]), now)
    b.last_paid = next_due(b, now.date())
    b.paid_on = now.date()
    b.last_amount = amount
    if b.variable:
        b.amount = amount
    repo.update(b)
    return res
