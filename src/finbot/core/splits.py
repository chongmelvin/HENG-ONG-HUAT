"""Debts between you and friends: owed balances, settlement, write-off (PRD 4.4)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from ..domain.models import Alloc, Expense, Receivable, Settlement
from ..domain.money import ZERO
from .audit import audit
from .ids import new_id
from .ledger import LedgerError


def open_receivables(repo, person_id: str | None = None) -> list[Receivable]:
    recs = [r for r in repo.all(Receivable) if r.status == "open" and r.outstanding > 0]
    if person_id:
        recs = [r for r in recs if r.person_id == person_id]
    return sorted(recs, key=lambda r: (r.created, r.id))


def credits(repo, person_id: str) -> Decimal:
    return sum((s.credit for s in repo.find(Settlement, person_id=person_id)), ZERO)


def balance(repo, person_id: str) -> Decimal:
    """Positive = they owe you; negative = you owe them (credit)."""
    return sum((r.outstanding for r in open_receivables(repo, person_id)), ZERO) - credits(repo, person_id)


def balances(repo) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for r in open_receivables(repo):
        out[r.person_id] = out.get(r.person_id, ZERO) + r.outstanding
    for s in repo.all(Settlement):
        if s.credit:
            out[s.person_id] = out.get(s.person_id, ZERO) - s.credit
    return {k: v for k, v in out.items() if v != 0}


def oldest_open_days(repo, person_id: str, today: date) -> int:
    recs = open_receivables(repo, person_id)
    return (today - recs[0].created).days if recs else 0


def settle(repo, now: datetime, person_id: str, amount: Decimal, account_id: str, on: date, *,
           confirm_credit: bool = False) -> Settlement:
    """Apply a repayment to the oldest debts first. Overpayment becomes a credit (needs confirm)."""
    if amount <= 0:
        raise LedgerError("The amount must be more than 0.")
    owed = balance(repo, person_id) if balance(repo, person_id) > 0 else ZERO
    if amount > owed and not confirm_credit:
        raise NeedsCreditConfirmation(owed=owed, excess=amount - owed)
    left = amount
    applied: list[Alloc] = []
    for r in open_receivables(repo, person_id):
        if left <= 0:
            break
        take = min(r.outstanding, left)
        r.settled += take
        if r.outstanding <= 0:
            r.status = "settled"
        repo.update(r)
        applied.append(Alloc(r.id, take))
        left -= take
    s = Settlement(id=new_id("st"), person_id=person_id, amount=amount, account_id=account_id, date=on,
                   applied=applied, credit=left)
    repo.add(s)
    audit(repo, now, "create", "settlements", s.id, f"{amount} person={person_id}")
    return s


class NeedsCreditConfirmation(Exception):
    def __init__(self, owed: Decimal, excess: Decimal) -> None:
        super().__init__("overpayment")
        self.owed, self.excess = owed, excess


def write_off(repo, now: datetime, person_id: str) -> Decimal:
    """Give up on what is still owed. The expense keeps counting in full, so it becomes personal spending."""
    total = ZERO
    for r in open_receivables(repo, person_id):
        total += r.outstanding
        r.status = "written_off"
        repo.update(r)
    audit(repo, now, "write_off", "receivables", person_id, str(total))
    return total


def chase_due(repo, today: date, chase_days: int = 7) -> list[tuple[str, Decimal, int]]:
    """People whose oldest debt is at least `chase_days` old: [(person_id, owed, days)]."""
    out = []
    for pid in {r.person_id for r in open_receivables(repo)}:
        days = oldest_open_days(repo, pid, today)
        if days >= chase_days:
            out.append((pid, balance(repo, pid), days))
    return sorted(out, key=lambda x: -x[2])
