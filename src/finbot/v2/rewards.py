"""Miles, points and cashback with expiry (PRD 6.3)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from ..core.audit import audit
from ..core.budgets import month_bounds
from ..core.ids import new_id
from ..core.ledger import LedgerError, active_expenses
from ..domain.enums import RewardType
from ..domain.models import Card, CardRule, Category, RewardBalance, RewardEvent, RewardProgram
from ..domain.money import ZERO
from .bestcard import _expense_class, evaluate

ALERTS = (90, 30, 7)


def ensure_program(repo, card: Card) -> RewardProgram:
    found = repo.find(RewardProgram, card_id=card.id)
    if found:
        return found[0]
    return repo.add(RewardProgram(id=new_id("rp"), name=f"{card.bank} {card.name}", kind=card.reward_type,
                                  value_per_unit=card.value_per_unit, card_id=card.id))


def balance_of(repo, program_id: str) -> RewardBalance:
    b = repo.find(RewardBalance, program_id=program_id)
    return b[0] if b else repo.add(RewardBalance(id=new_id("rb"), program_id=program_id, balance=ZERO))


def _event(repo, program_id: str, on: date, kind: str, amount: Decimal, source="estimated", note=""):
    repo.add(RewardEvent(id=new_id("re"), program_id=program_id, date=on, kind=kind, amount=amount, source=source, note=note))
    b = balance_of(repo, program_id)
    b.balance += amount if kind in ("earn", "adjust") else -abs(amount) if kind in ("redeem", "expire") else amount
    repo.update(b)


def estimate_month(repo, card: Card, year: int, month: int) -> Decimal:
    """Estimate earn for a month by replaying each card expense through your earn rules in date order."""
    s, e = month_bounds(year, month)
    cats = {c.id: c.name for c in repo.all(Category)}
    total = ZERO
    spent_by_class: dict[str, Decimal] = {}
    for ex in sorted([x for x in active_expenses(repo) if s <= x.spend_date <= e], key=lambda x: (x.spend_date, x.id)):
        amt = sum((p.amount for p in ex.payments if p.account_id == card.account_id), ZERO)
        if not amt:
            continue
        cls = _expense_class(repo, ex, cats)
        opt = evaluate(repo, card, cls, amt, ex.spend_date)
        if opt:
            used = spent_by_class.get(cls, ZERO)
            rule = opt.rule
            if rule and rule.cap is not None and rate_is_bonus(opt, rule) and used + amt > rule.cap:
                bonus_part = max(rule.cap - used, ZERO)
                units = bonus_part * rule.rate + (amt - bonus_part) * rule.fallback_rate
            else:
                units = amt * opt.rate
            total += units
        spent_by_class[cls] = spent_by_class.get(cls, ZERO) + amt
    return total.quantize(Decimal("0.01"))


def rate_is_bonus(opt, rule: CardRule) -> bool:
    return opt.rate == rule.rate


def record_estimate(repo, now: datetime, card: Card, year: int, month: int) -> Decimal:
    prog = ensure_program(repo, card)
    earn = estimate_month(repo, card, year, month)
    _event(repo, prog.id, month_bounds(year, month)[1], "earn", earn, "estimated", f"{year}-{month:02d}")
    return earn


def confirm_balance(repo, now: datetime, program_id: str, actual: Decimal, expires: Optional[date] = None) -> Decimal:
    """Monthly confirmation against the statement or app. Differences become an Adjustment event."""
    b = balance_of(repo, program_id)
    diff = actual - b.balance
    if diff != 0:
        _event(repo, program_id, now.date(), "adjust", diff, "confirmed", "monthly confirmation")
    b = balance_of(repo, program_id)
    b.last_confirmed = now.date()
    if expires:
        b.expires = expires
    repo.update(b)
    return diff


def redeem(repo, now: datetime, program_id: str, amount: Decimal, note: str = "") -> None:
    b = balance_of(repo, program_id)
    if amount > b.balance:
        raise LedgerError(f"You only have {b.balance:g} to redeem.")
    _event(repo, program_id, now.date(), "redeem", amount, "confirmed", note)


def expiry_alerts(repo, today: date) -> list[tuple[RewardProgram, RewardBalance, int]]:
    out = []
    for b in repo.all(RewardBalance):
        if b.expires and b.balance > 0:
            days = (b.expires - today).days
            if days in ALERTS or days <= 0:
                out.append((repo.get(RewardProgram, b.program_id), b, days))
    return out


def value_of(program: RewardProgram, units: Decimal) -> Decimal:
    return (units * program.value_per_unit).quantize(Decimal("0.01"))


def annual_value_vs_fee(repo, card: Card, year: int) -> dict:
    prog = ensure_program(repo, card)
    earned = sum((e.amount for e in repo.find(RewardEvent, program_id=prog.id, kind="earn") if e.date.year == year), ZERO)
    value = earned if card.reward_type == RewardType.CASHBACK else earned * card.value_per_unit
    return {"earned": earned, "value": value.quantize(Decimal("0.01")), "fee": card.annual_fee,
            "net": (value - card.annual_fee).quantize(Decimal("0.01"))}
