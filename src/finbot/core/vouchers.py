"""Vouchers and credits (CDC, Culture Pass, ...). Rules are yours; the bot assumes none (PRD 5.4)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from ..domain.models import Voucher, VoucherUsage
from ..domain.money import ZERO
from .audit import audit
from .ids import new_id
from .indicators import expiry_light
from .ledger import LedgerError


def active(repo, scheme: str | None = None, on: date | None = None) -> list[Voucher]:
    out = [v for v in repo.all(Voucher) if v.status == "active" and v.remaining > 0]
    if scheme:
        out = [v for v in out if v.scheme.lower() == scheme.lower()]
    if on:
        out = [v for v in out if v.expires >= on]
    return sorted(out, key=lambda v: v.expires)


def add_voucher(repo, now: datetime, scheme: str, amount: Decimal, expires: date, **kw) -> Voucher:
    if amount <= 0:
        raise LedgerError("The amount must be more than 0.")
    v = Voucher(id=new_id("vo"), scheme=scheme, original=amount, remaining=amount, expires=expires,
                last_verified=now.date(), **kw)
    repo.add(v)
    audit(repo, now, "create", "vouchers", v.id, f"{scheme} {amount}")
    return v


def plan_consumption(repo, scheme: str, amount: Decimal, on: date) -> list[tuple[Voucher, Decimal]]:
    """Earliest-expiring eligible batch first. Raises InsufficientVoucher with what is left."""
    batches = active(repo, scheme, on)
    left, plan = amount, []
    for b in batches:
        take = min(b.remaining, left)
        if take > 0:
            plan.append((b, take))
            left -= take
        if left <= 0:
            break
    if left > 0:
        raise InsufficientVoucher(scheme, remaining=amount - left)
    return plan


class InsufficientVoucher(LedgerError):
    def __init__(self, scheme: str, remaining: Decimal) -> None:
        super().__init__(f"{scheme} has only {remaining} left.")
        self.scheme, self.left = scheme, remaining


def apply_consumption(repo, batch: Voucher, amount: Decimal, expense_id: str, on: date) -> None:
    b = repo.get(Voucher, batch.id)
    b.remaining -= amount
    if b.remaining <= 0:
        b.status = "used"
    repo.update(b)
    repo.add(VoucherUsage(id=new_id("vu"), voucher_id=b.id, expense_id=expense_id, amount=amount, date=on))


def restore(repo, usage: VoucherUsage) -> None:
    b = repo.get(Voucher, usage.voucher_id)
    if b:
        b.remaining += usage.amount
        if b.status == "used":
            b.status = "active"
        repo.update(b)
    repo.delete(VoucherUsage, usage.id)


def expire_overdue(repo, now: datetime) -> list[Voucher]:
    """Vouchers past expiry with a balance. The bot asks before marking them expired (PRD 5.4)."""
    return [v for v in repo.all(Voucher) if v.status == "active" and v.remaining > 0 and v.expires < now.date()]


def mark_expired(repo, now: datetime, voucher_id: str) -> Decimal:
    v = repo.get(Voucher, voucher_id)
    lost = v.remaining
    v.status = "expired"
    repo.update(v)
    audit(repo, now, "expire", "vouchers", v.id, f"lost {lost}")
    return lost


def extend(repo, now: datetime, voucher_id: str, new_expiry: date) -> Voucher:
    v = repo.get(Voucher, voucher_id)
    v.expires = new_expiry
    if v.status == "expired":
        v.status = "active"
    repo.update(v)
    audit(repo, now, "extend", "vouchers", v.id, str(new_expiry))
    return v


def adjust_balance(repo, now: datetime, voucher_id: str, new_remaining: Decimal, reason: str) -> Voucher:
    v = repo.get(Voucher, voucher_id)
    old = v.remaining
    v.remaining = new_remaining
    repo.update(v)
    audit(repo, now, "adjust", "vouchers", v.id, f"{old} -> {new_remaining}: {reason}")
    return v


def summary(repo, today: date) -> list[dict]:
    rows = []
    for v in active(repo):
        days = (v.expires - today).days
        rows.append({"voucher": v, "days_left": days, "light": expiry_light(days)})
    return rows


def expiry_alerts(repo, today: date, thresholds=(60, 30, 7)) -> list[tuple[Voucher, int]]:
    """Vouchers that hit an alert threshold exactly today."""
    return [(v, (v.expires - today).days) for v in active(repo) if (v.expires - today).days in thresholds]
