"""Savings buckets (PRD 5.1): virtual allocations that float over combined assets."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from ..domain.models import Allocation, SavingsBucket
from ..domain.money import ZERO
from .ids import new_id
from .ledger import LedgerError
from .lookup import norm


def create_bucket(repo, name: str, target: Decimal = ZERO, target_date: Optional[date] = None) -> SavingsBucket:
    if any(norm(b.name) == norm(name) for b in repo.all(SavingsBucket)):
        raise LedgerError(f"{name} already exists.")
    return repo.add(SavingsBucket(id=new_id("sb"), name=name, target=target, target_date=target_date))


def allocate(repo, bucket_id: str, amount: Decimal, on: date, note: str = "") -> Allocation:
    return repo.add(Allocation(id=new_id("al"), bucket_id=bucket_id, amount=amount, date=on, note=note))


def balance(repo, bucket_id: str) -> Decimal:
    return sum((a.amount for a in repo.find(Allocation, bucket_id=bucket_id)), ZERO)


def progress(repo, today: date) -> list[dict]:
    rows = []
    for b in repo.all(SavingsBucket):
        bal = balance(repo, b.id)
        pace = _monthly_pace(repo, b.id, today)
        eta = None
        if b.target > bal and pace > 0:
            eta = today + timedelta(days=int((b.target - bal) / pace * 30))
        rows.append({"bucket": b, "balance": bal, "pct": float(bal / b.target * 100) if b.target else 0.0, "eta": eta})
    return rows


def _monthly_pace(repo, bucket_id: str, today: date) -> Decimal:
    since = today - timedelta(days=90)
    recent = sum((a.amount for a in repo.find(Allocation, bucket_id=bucket_id) if a.date >= since), ZERO)
    return recent / 3


def check_total(repo, assets_total: Decimal) -> Optional[Decimal]:
    """Positive = buckets add up to more than the assets available (warn)."""
    total = sum((balance(repo, b.id) for b in repo.all(SavingsBucket)), ZERO)
    return total - assets_total if total > assets_total else None
