"""Reimbursements (PRD 5.3). A payout is not income; it lowers that expense's net spend."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from ..domain.enums import ClaimStatus
from ..domain.models import Claim
from ..domain.money import ZERO
from .audit import audit
from .ids import new_id
from .ledger import LedgerError


def pending(repo) -> list[Claim]:
    return [c for c in repo.all(Claim) if c.status in (ClaimStatus.UNCLAIMED, ClaimStatus.SUBMITTED) and c.outstanding > 0]


def submit(repo, now: datetime, claimant: str) -> tuple[str, list[Claim]]:
    """Group a claimant's unclaimed expenses into one batch."""
    todo = [c for c in repo.all(Claim) if c.status == ClaimStatus.UNCLAIMED and c.claimant.lower() == claimant.lower()]
    if not todo:
        raise LedgerError(f"Nothing unclaimed for {claimant}.")
    batch = new_id("ba")
    for c in todo:
        c.status, c.batch, c.submitted = ClaimStatus.SUBMITTED, batch, now.date()
        repo.update(c)
    audit(repo, now, "submit", "claims", batch, f"{claimant} {sum((c.amount for c in todo), ZERO)}")
    return batch, todo


def pay(repo, now: datetime, claimant: str, amount: Decimal, account_id: str, *, confirm_excess: bool = False) -> list[Claim]:
    """Apply a payout to the claimant's oldest open claims. Excess needs confirmation (PRD examples)."""
    open_ = sorted([c for c in pending(repo) if c.claimant.lower() == claimant.lower()], key=lambda c: (c.submitted or date.min, c.id))
    owed = sum((c.outstanding for c in open_), ZERO)
    if amount <= 0:
        raise LedgerError("The amount must be more than 0.")
    if amount > owed and not confirm_excess:
        raise ExcessPayout(owed, amount - owed)
    left, touched = amount, []
    for c in open_:
        if left <= 0:
            break
        take = min(c.outstanding, left)
        c.paid_amount += take
        c.paid_date, c.account_id = now.date(), account_id
        if c.outstanding <= 0:
            c.status = ClaimStatus.PAID
        repo.update(c)
        touched.append(c)
        left -= take
    audit(repo, now, "paid", "claims", claimant, str(amount))
    return touched


class ExcessPayout(LedgerError):
    def __init__(self, owed: Decimal, excess: Decimal) -> None:
        super().__init__("payout is more than the open claim")
        self.owed, self.excess = owed, excess


def reject(repo, now: datetime, claim_id: str) -> Claim:
    """Rejected claims become personal spending (net spend stays at the full amount)."""
    c = repo.get(Claim, claim_id)
    c.status = ClaimStatus.REJECTED
    repo.update(c)
    audit(repo, now, "reject", "claims", claim_id)
    return c


def chase_due(repo, today: date, days: int = 14) -> list[Claim]:
    return [c for c in repo.all(Claim) if c.status == ClaimStatus.SUBMITTED and c.submitted and (today - c.submitted).days >= days]
