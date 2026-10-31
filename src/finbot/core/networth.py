"""Accounts, snapshots, reconciliation and net worth (PRD 5.1).

Balances are derived from flows (opening balance + every transaction after the first snapshot).
Reconciliation compares those with the balances you type in each month, per account, with zero
tolerance. Only what is left after you have tried to explain it is written off as an Adjustment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from ..domain.enums import ACTIVE, AccountType, AssetGroup
from ..domain.models import (Account, Adjustment, Balance, Claim, Expense, Holding, Income, Receivable, Refund,
                             Settings, Settlement, Snapshot, Transfer)
from ..domain.money import ZERO
from .audit import audit
from .ids import new_id
from .indicators import networth_light, reconcile_icon
from .ledger import LedgerError, NetIndex, active_expenses


def fixed_accounts(repo) -> list[Account]:
    return [a for a in repo.all(Account) if a.status == ACTIVE and a.asset_group == AssetGroup.FIXED
            and a.type != AccountType.VOUCHER]


def _after(settings: Settings, d: date) -> bool:
    """Entries dated on or before the first snapshot count in reports but not in balances."""
    return settings.first_snapshot_date is None or d > settings.first_snapshot_date


def computed_balances(repo, settings: Settings, as_of: Optional[date] = None) -> dict[str, Decimal]:
    """Expected balance of every account from opening balance plus flows. Liabilities are negative."""
    as_of = as_of or date.max
    bal = {a.id: a.opening_balance for a in repo.all(Account)}

    def add(acct: str, amt: Decimal, d: date):
        if acct in bal and _after(settings, d) and d <= as_of:
            bal[acct] += amt

    for e in active_expenses(repo):
        for p in e.payments:
            add(p.account_id, -p.amount, e.spend_date)
    for i in repo.all(Income):
        if i.status == ACTIVE:
            add(i.account_id, i.amount, i.date)
    for t in repo.all(Transfer):
        if t.status == ACTIVE:
            add(t.from_account, -t.amount, t.date)
            add(t.to_account, t.amount, t.date)
    for s in repo.all(Settlement):
        add(s.account_id, s.amount, s.date)
    for r in repo.all(Refund):
        if r.status == ACTIVE:
            add(r.account_id, r.amount, r.date)
    for c in repo.all(Claim):
        if c.paid_amount > 0 and c.account_id and c.paid_date:
            add(c.account_id, c.paid_amount, c.paid_date)
    for a in repo.all(Adjustment):
        add(a.account_id, a.amount, a.date)
    return bal


def owed_total(repo) -> Decimal:
    """Money owed to you: open receivables plus unpaid claims. Counts as a fixed asset."""
    r = sum((x.outstanding for x in repo.all(Receivable)), ZERO)
    c = sum((x.outstanding for x in repo.all(Claim)), ZERO)
    return r + c


def variable_total(repo) -> Decimal:
    return sum((h.value for h in repo.all(Holding) if h.status == ACTIVE), ZERO)


@dataclass
class AccountGap:
    account: Account
    expected: Decimal
    entered: Decimal

    @property
    def gap(self) -> Decimal:
        return self.entered - self.expected


@dataclass
class Reconciliation:
    rows: list[AccountGap]
    first: bool = False

    @property
    def gap(self) -> Decimal:
        return sum((r.gap for r in self.rows), ZERO)

    @property
    def movers(self) -> list[AccountGap]:
        return sorted([r for r in self.rows if r.gap != 0], key=lambda r: -abs(r.gap))

    @property
    def icon(self) -> str:
        return reconcile_icon(self.gap)


def reconcile(repo, settings: Settings, entered: dict[str, Decimal], on: date) -> Reconciliation:
    if settings.first_snapshot_date is None:
        return Reconciliation([], first=True)
    exp = computed_balances(repo, settings, on)
    rows = [AccountGap(a, exp.get(a.id, ZERO), entered[a.id]) for a in fixed_accounts(repo) if a.id in entered]
    return Reconciliation(rows)


def take_snapshot(repo, settings: Settings, now: datetime, entered: dict[str, Decimal], *, write_off: bool = False,
                  on: Optional[date] = None) -> tuple[Snapshot, Reconciliation]:
    """Store a snapshot. The first one sets opening balances (clean slate, no history imported)."""
    on = on or now.date()
    for a in fixed_accounts(repo):
        if a.id not in entered:
            raise LedgerError(f"Missing a balance for {a.name}. Enter it or mark it unchanged.")
    recon = reconcile(repo, settings, entered, on)
    written = ZERO
    if recon.first:
        for a in fixed_accounts(repo):
            a.opening_balance = entered[a.id]
            repo.update(a)
        settings.first_snapshot_date = on
        repo.update(settings)
    elif write_off and recon.gap != 0:
        for r in recon.rows:
            if r.gap != 0:
                repo.add(Adjustment(id=new_id("ad"), account_id=r.account.id, amount=r.gap, reason="unexplained", date=on))
                written += r.gap
        audit(repo, now, "write_off", "adjustments", "", f"gap {written}")
    owed, var = owed_total(repo), variable_total(repo)
    fixed = sum(entered.values(), ZERO) + owed
    snap = Snapshot(id=new_id("sn"), date=on, balances=[Balance(k, v) for k, v in entered.items()],
                    owed=owed, variable=var, fixed=fixed, net_worth=fixed + var, gap=recon.gap, written_off=written)
    repo.add(snap)
    return snap, recon


def snapshots(repo) -> list[Snapshot]:
    return sorted(repo.all(Snapshot), key=lambda s: s.date)


def previous_snapshot(repo, before: date) -> Optional[Snapshot]:
    s = [x for x in snapshots(repo) if x.date < before]
    return s[-1] if s else None


def liquid_assets(snap: Snapshot, repo) -> Decimal:
    liquid_types = {AccountType.BANK, AccountType.CASH, AccountType.EWALLET}
    types = {a.id: a.type for a in repo.all(Account)}
    return sum((b.amount for b in snap.balances if types.get(b.account_id) in liquid_types), ZERO)


def runway_months(repo, snap: Snapshot, avg_monthly_net_spend: Decimal) -> Optional[Decimal]:
    if avg_monthly_net_spend <= 0:
        return None
    return (liquid_assets(snap, repo) / avg_monthly_net_spend).quantize(Decimal("0.1"))


@dataclass
class Bridge:
    opening: Decimal
    income: Decimal
    net_spend: Decimal
    owed_created: Decimal
    market: Decimal
    adjustments: Decimal
    closing: Decimal

    @property
    def unexplained(self) -> Decimal:
        return self.closing - (self.opening + self.income - self.net_spend + self.owed_created + self.market + self.adjustments)


def bridge(repo, settings: Settings, prev: Snapshot, cur: Snapshot) -> Bridge:
    """Waterfall from one snapshot to the next on a cash basis, so it always adds up exactly."""
    lo, hi = prev.date, cur.date
    inc = sum((i.amount for i in repo.all(Income) if i.status == ACTIVE and lo < i.date <= hi), ZERO)
    paid = sum((p.amount for e in active_expenses(repo) if lo < e.spend_date <= hi for p in e.payments
                if _is_real(repo, p.account_id)), ZERO)
    repaid = sum((s.amount for s in repo.all(Settlement) if lo < s.date <= hi), ZERO)
    refunds = sum((r.amount for r in repo.all(Refund) if r.status == ACTIVE and lo < r.date <= hi), ZERO)
    claims_in = sum((c.paid_amount for c in repo.all(Claim) if c.paid_date and lo < c.paid_date <= hi), ZERO)
    net_spend = paid - repaid - refunds - claims_in
    new_owed = cur.owed - prev.owed + repaid + claims_in
    contrib = _contributions(repo, lo, hi)
    market = (cur.variable - prev.variable) - contrib
    adj = sum((a.amount for a in repo.all(Adjustment) if lo < a.date <= hi), ZERO)
    return Bridge(prev.net_worth, inc, net_spend, new_owed, market, adj, cur.net_worth)


def _is_real(repo, account_id: str) -> bool:
    a = repo.get(Account, account_id)
    return bool(a and a.type != AccountType.VOUCHER)


def _contributions(repo, lo: date, hi: date) -> Decimal:
    var_ids = {a.id for a in repo.all(Account) if a.asset_group == AssetGroup.VARIABLE or a.type == AccountType.BROKERAGE}
    return sum((t.amount for t in repo.all(Transfer) if t.status == ACTIVE and lo < t.date <= hi and t.to_account in var_ids), ZERO)


def net_worth_light(cur: Snapshot, prev: Optional[Snapshot]) -> str:
    return networth_light(cur.net_worth - prev.net_worth, prev.net_worth) if prev else ""
