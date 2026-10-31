"""Loans (PRD 6.7). Interest counts as spending; principal repaid is a transfer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from ..core.audit import audit
from ..core.ids import new_id
from ..core.ledger import LedgerError
from ..domain.enums import ACTIVE
from ..domain.models import Loan
from ..domain.money import ZERO

CENT = Decimal("0.01")


def add(repo, now: datetime, **kw) -> Loan:
    l = repo.add(Loan(id=new_id("lo"), **kw))
    audit(repo, now, "create", "loans", l.id, l.lender)
    return l


def split_instalment(loan: Loan, amount: Decimal) -> tuple[Decimal, Decimal]:
    """(interest, principal) for one monthly instalment on the current balance."""
    interest = (loan.balance * loan.rate / 12).quantize(CENT, rounding=ROUND_HALF_UP)
    interest = min(interest, amount)
    return interest, amount - interest


def apply_payment(repo, now: datetime, loan_id: str, amount: Decimal) -> tuple[Decimal, Decimal]:
    loan = repo.get(Loan, loan_id)
    if amount <= 0:
        raise LedgerError("The amount must be more than 0.")
    interest, principal = split_instalment(loan, amount)
    principal = min(principal, loan.balance)
    loan.balance -= principal
    if loan.balance <= 0:
        loan.status = "paid_off"
    repo.update(loan)
    return interest, principal


@dataclass
class Scenario:
    months: int
    total_interest: Decimal
    payoff: date


def payoff(loan: Loan, today: date, extra: Decimal = ZERO) -> Optional[Scenario]:
    bal, months, tot = loan.balance, 0, ZERO
    pay = loan.instalment + extra
    while bal > 0 and months < 600:
        i = (bal * loan.rate / 12).quantize(CENT, rounding=ROUND_HALF_UP)
        if pay <= i:
            return None
        tot += i
        bal = bal + i - pay
        months += 1
    y, m = divmod(today.month - 1 + months, 12)
    return Scenario(months, tot, date(today.year + y, m + 1, min(loan.pay_day, 28)))


def active(repo) -> list[Loan]:
    return repo.find(Loan, status=ACTIVE)
