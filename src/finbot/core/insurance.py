"""Insurance policies, premiums and summaries (PRD 5.2). Full policy numbers are never stored."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from ..domain.enums import ACTIVE
from ..domain.models import Bill, Insurance
from ..domain.money import ZERO
from .audit import audit
from .bills import STEP
from .ids import new_id
from .ledger import LedgerError

PER_YEAR = {"monthly": 12, "quarterly": 4, "half_yearly": 2, "yearly": 1}


def add_policy(repo, now: datetime, *, policy_number: str = "", **kw) -> tuple[Insurance, bool]:
    """Returns (policy, number_was_truncated). Only the last 4 characters are kept."""
    if kw.get("frequency") not in PER_YEAR:
        raise LedgerError("Frequency must be monthly, quarterly, half_yearly or yearly.")
    trunc = len(policy_number) > 4
    ins = Insurance(id=new_id("is"), policy_last4=policy_number[-4:], **kw)
    repo.add(ins)
    repo.add(Bill(id=new_id("bi"), name=f"{ins.insurer} {ins.product}", due_day=ins.next_due.day, amount=ins.premium,
                  recurrence=_bill_rec(ins.frequency), anchor_month=ins.next_due.month, kind="insurance", ref_id=ins.id,
                  account_id=ins.pay_account_id, created=now.date()))
    audit(repo, now, "create", "insurance", ins.id, f"{ins.insurer} {ins.product}")
    return ins, trunc


def _bill_rec(freq: str) -> str:
    return freq


def active(repo) -> list[Insurance]:
    return [i for i in repo.all(Insurance) if i.status == ACTIVE and (i.end is None or i.end >= date.min)]


def annual_premium(i: Insurance) -> Decimal:
    return i.premium * PER_YEAR[i.frequency]


def summary(repo, today: date) -> dict:
    pols = active(repo)
    by_type: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for p in pols:
        by_type[p.type] += annual_premium(p)
    total = sum(by_type.values(), ZERO)
    due = sorted([(p, p.next_due) for p in pols if 0 <= (p.next_due - today).days <= 90], key=lambda x: x[1])
    ending = [p for p in pols if p.end and 0 <= (p.end - today).days <= 180]
    return {"policies": pols, "annual": total, "monthly": (total / 12).quantize(Decimal("0.01")),
            "by_type": dict(by_type), "due_90": due, "ending": ending}


def coverage_of(repo, text: str) -> list[Insurance]:
    t = text.lower()
    return [i for i in active(repo) if t in i.insurer.lower() or t in i.product.lower()]
