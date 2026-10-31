"""Big-ticket items, warranties and receipts (PRD 5.4)."""
from __future__ import annotations

import calendar
import difflib
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from ..domain.models import Expense, Item, Settings
from .audit import audit
from .ids import new_id
from .indicators import expiry_light
from .ledger import LedgerError
from .lookup import norm


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def should_prompt(settings: Settings, exp: Expense, tagged_big: bool) -> bool:
    """Optional prompt at S$100 or more, or a big-ticket tag on any expense."""
    return tagged_big or (settings.big_ticket_prompt and exp.amount >= settings.big_ticket_threshold)


def create_item(repo, now: datetime, exp: Expense, name: str, warranty_months: int = 0, **kw) -> Item:
    it = Item(id=new_id("it"), name=name, price=exp.amount, purchase_date=exp.spend_date, expense_id=exp.id,
              warranty_months=warranty_months,
              warranty_end=add_months(exp.spend_date, warranty_months) if warranty_months else None, **kw)
    repo.add(it)
    audit(repo, now, "create", "items", it.id, name)
    return it


def attach_receipt(repo, item_id: str, link: str, file_id: str) -> Item:
    it = repo.get(Item, item_id)
    it.receipt_link, it.file_id = link, file_id
    repo.update(it)
    return it


def find_item(repo, text: str) -> Optional[Item]:
    items = repo.all(Item)
    t = norm(text)
    for it in items:
        if t and (t == norm(it.name) or t in norm(it.name)):
            return it
    close = difflib.get_close_matches(t, [norm(i.name) for i in items], n=1, cutoff=0.6)
    return next((i for i in items if norm(i.name) == close[0]), None) if close else None


def warranty_alerts(repo, today: date, thresholds=(60, 30)) -> list[tuple[Item, int, str]]:
    out = []
    for it in repo.all(Item):
        if it.status == "in_use" and it.warranty_end:
            days = (it.warranty_end - today).days
            if days in thresholds:
                out.append((it, days, expiry_light(days)))
    return out


def expiring_within(repo, today: date, days: int = 60) -> list[tuple[Item, int]]:
    return sorted([(i, (i.warranty_end - today).days) for i in repo.all(Item)
                   if i.status == "in_use" and i.warranty_end and 0 <= (i.warranty_end - today).days <= days], key=lambda x: x[1])


def mark_sold(repo, now: datetime, item_id: str, price: Decimal) -> Item:
    it = repo.get(Item, item_id)
    it.status, it.sale_price = "sold", price
    repo.update(it)
    audit(repo, now, "sold", "items", item_id, str(price))
    return it
