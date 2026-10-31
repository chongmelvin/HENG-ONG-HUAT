"""Annual expenses calendar and sinking funds (PRD 6.7). Never touches the Monthly budget."""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from ..core import savings
from ..core.budgets import TOTAL_Y, limit_in_force
from ..core.ids import new_id
from ..domain.models import AnnualItem
from ..domain.money import ZERO


def add(repo, name: str, amount: Decimal, month: int, savings_bucket_id: str = "") -> AnnualItem:
    if not 1 <= month <= 12:
        raise ValueError("month must be 1 to 12")
    return repo.add(AnnualItem(id=new_id("an"), name=name, amount=amount, month=month, savings_bucket_id=savings_bucket_id))


def monthly_set_aside(item: AnnualItem) -> Decimal:
    return (item.amount / 12).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def run_sinking_funds(repo, on: date) -> list[tuple[AnnualItem, Decimal]]:
    """Each month, allocate amount/12 to the item's savings bucket. Virtual only."""
    out = []
    for it in repo.all(AnnualItem):
        if it.savings_bucket_id:
            amt = monthly_set_aside(it)
            savings.allocate(repo, it.savings_bucket_id, amt, on, note=f"sinking fund: {it.name}")
            out.append((it, amt))
    return out


def forecast(repo, year: int, yearly_spent: Decimal) -> dict:
    known = sum((i.amount for i in repo.all(AnnualItem)), ZERO)
    limit = limit_in_force(repo, TOTAL_Y, date(year, 1, 1)) or ZERO
    return {"known": known, "limit": limit, "spent": yearly_spent, "unplanned": limit - known - yearly_spent,
            "calendar": sorted(repo.all(AnnualItem), key=lambda i: (i.month, i.name))}
