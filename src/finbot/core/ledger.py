"""Creating, editing and deleting transactions, plus the net-spend definition.

Net spend (PRD section 1) = amount paid - friend repayments - claim payouts - linked refunds.
The full amount counts until money comes back.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from ..domain.enums import ACTIVE, AccountType, Bucket
from ..domain.models import (Account, Claim, ClaimStatus, Expense, Income, Payment, Receivable,
                             Refund, Settings, Transfer, VoucherUsage)
from ..domain.money import ZERO, split_equal, split_percent
from .audit import audit
from .ids import new_id


class LedgerError(ValueError):
    """User-correctable problem; message is safe to show."""


# --------------------------------------------------------------------- net spend
class NetIndex:
    """Pre-computed lookups so reports can compute net spend for thousands of rows."""

    def __init__(self, repo) -> None:
        self.repaid: dict[str, Decimal] = defaultdict(lambda: ZERO)
        self.claim_paid: dict[str, Decimal] = defaultdict(lambda: ZERO)
        self.refunded: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for r in repo.all(Receivable):
            self.repaid[r.expense_id] += r.settled
        for c in repo.all(Claim):
            self.claim_paid[c.expense_id] += c.paid_amount
        for f in repo.all(Refund):
            if f.status == ACTIVE and f.expense_id:
                self.refunded[f.expense_id] += f.amount

    def net(self, e: Expense) -> Decimal:
        n = e.amount - self.repaid[e.id] - self.claim_paid[e.id] - self.refunded[e.id]
        return max(n, ZERO)


def active_expenses(repo) -> list[Expense]:
    return [e for e in repo.all(Expense) if e.status == ACTIVE]


# --------------------------------------------------------------------- creation
@dataclass
class ExpenseInput:
    amount: Decimal
    category_id: str
    bucket: Bucket
    payments: list[Payment]
    spend_date: date
    description: str = ""
    people: list[str] = field(default_factory=list)       # person ids present
    location: str = ""
    tags: list[str] = field(default_factory=list)
    split_mode: str = ""                                   # "", equal, custom, percent, treat
    split_values: dict[str, Decimal] = field(default_factory=dict)  # person_id -> amount or percent
    claimable: bool = False
    claimant: str = ""
    item: str = ""
    note: str = ""
    trip_id: str = ""
    currency: str = "SGD"
    foreign_amount: Optional[Decimal] = None
    fx_rate: Optional[Decimal] = None
    idem_key: str = ""


@dataclass
class ExpenseResult:
    expense: Expense
    receivables: list[Receivable]
    claim: Optional[Claim] = None


def compute_shares(inp: ExpenseInput) -> tuple[Decimal, dict[str, Decimal]]:
    """Return (my_share, {person_id: their_share})."""
    total = inp.amount
    people = list(dict.fromkeys(inp.people))
    mode = inp.split_mode
    if not mode or mode == "treat" or not people:
        return total, {}
    if mode == "equal":
        mine, others = split_equal(total, len(people) + 1)
        return mine, dict(zip(people, others))
    if mode == "custom":
        shares = {p: inp.split_values[p] for p in people if p in inp.split_values}
        if sum(shares.values(), ZERO) > total:
            raise LedgerError(f"Shares add up to {sum(shares.values(), ZERO)}, more than the {total} total.")
        return total - sum(shares.values(), ZERO), shares
    if mode == "percent":
        pcts = [inp.split_values.get(p, ZERO) for p in people]
        if sum(pcts, ZERO) > 100:
            raise LedgerError("Percentages add up to more than 100%.")
        amounts = split_percent(total, pcts)
        return total - sum(amounts, ZERO), dict(zip(people, amounts))
    raise LedgerError(f"Unknown split mode {mode}")


def create_expense(repo, settings: Settings, inp: ExpenseInput, now: datetime) -> ExpenseResult:
    from . import vouchers  # local import avoids a cycle

    if inp.amount <= 0:
        raise LedgerError("The amount must be more than 0.")
    if sum((p.amount for p in inp.payments), ZERO) != inp.amount:
        raise LedgerError("Payments must add up to the total amount.")
    mine, others = compute_shares(inp)
    today = now.date()
    exp = Expense(
        id=new_id("ex"), amount=inp.amount, category_id=inp.category_id, bucket=inp.bucket,
        payments=inp.payments, spend_date=inp.spend_date, entry_date=today, my_share=mine,
        currency=inp.currency, foreign_amount=inp.foreign_amount, fx_rate=inp.fx_rate,
        description=inp.description, tags=list(inp.tags), people=list(inp.people), location=inp.location,
        split_mode=inp.split_mode, claimable=inp.claimable, trip_id=inp.trip_id, item=inp.item,
        note=inp.note, idem_key=inp.idem_key, created_at=now,
    )
    # voucher payments: consume earliest-expiring batches first (validates before writing)
    consumed = []
    for p in inp.payments:
        acct = repo.get(Account, p.account_id)
        if acct and acct.type == AccountType.VOUCHER:
            consumed += vouchers.plan_consumption(repo, acct.name, p.amount, inp.spend_date)
    repo.add(exp)
    for batch, amt in consumed:
        vouchers.apply_consumption(repo, batch, amt, exp.id, inp.spend_date)
    recs = []
    for pid, share in others.items():
        if share > 0:
            r = Receivable(id=new_id("rc"), expense_id=exp.id, person_id=pid, amount=share, created=inp.spend_date)
            repo.add(r)
            recs.append(r)
    claim = None
    if inp.claimable:
        claim = Claim(id=new_id("cl"), expense_id=exp.id, claimant=inp.claimant or "Employer", amount=inp.amount)
        repo.add(claim)
    audit(repo, now, "create", "expenses", exp.id, f"{inp.amount} {inp.description}")
    return ExpenseResult(exp, recs, claim)


def create_income(repo, now: datetime, *, amount: Decimal, source: str, account_id: str, on: date,
                  gross=None, bonus=None, deductions=None, recurring=False, note="") -> Income:
    if amount <= 0:
        raise LedgerError("The amount must be more than 0.")
    inc = Income(id=new_id("in"), amount=amount, source=source, account_id=account_id, date=on,
                 recurring=recurring, gross=gross, bonus=bonus, deductions=deductions, note=note)
    repo.add(inc)
    audit(repo, now, "create", "incomes", inc.id, f"{amount} {source}")
    return inc


def check_payslip(gross: Optional[Decimal], deductions: Optional[Decimal], net: Decimal) -> Optional[Decimal]:
    """Return the implied net if the breakdown does not match, else None."""
    if gross is None or deductions is None:
        return None
    implied = gross - deductions
    return implied if implied != net else None


def create_transfer(repo, now: datetime, *, from_account: str, to_account: str, amount: Decimal, on: date, note="") -> Transfer:
    if amount <= 0:
        raise LedgerError("The amount must be more than 0.")
    if from_account == to_account:
        raise LedgerError("Pick two different accounts.")
    t = Transfer(id=new_id("tr"), from_account=from_account, to_account=to_account, amount=amount, date=on, note=note)
    repo.add(t)
    audit(repo, now, "create", "transfers", t.id, f"{amount}")
    return t


# --------------------------------------------------------------------- refunds
def create_refund(repo, now: datetime, *, amount: Decimal, account_id: str, on: date,
                  expense_id: str = "", category_id: str = "", note: str = "") -> Refund:
    if amount <= 0:
        raise LedgerError("The amount must be more than 0.")
    if expense_id:
        exp = repo.get(Expense, expense_id)
        if exp is None:
            raise LedgerError("I can't find that expense.")
        already = sum((f.amount for f in repo.find(Refund, expense_id=expense_id, status=ACTIVE)), ZERO)
        if amount + already > exp.amount:
            raise LedgerError(f"The refund can't be more than the {exp.amount} expense.")
        category_id = category_id or exp.category_id
    r = Refund(id=new_id("rf"), amount=amount, account_id=account_id, date=on,
               expense_id=expense_id, category_id=category_id, note=note)
    repo.add(r)
    audit(repo, now, "create", "refunds", r.id, f"{amount}")
    return r


# --------------------------------------------------------------------- delete / undo
def delete_expense(repo, now: datetime, expense_id: str) -> dict:
    """Soft-delete an expense and unwind its links (PRD 4.4 'Deleting linked entries').

    Returns a summary of what happened, which the bot shows after confirmation.
    """
    from . import vouchers

    exp = repo.get(Expense, expense_id)
    if exp is None or exp.status != ACTIVE:
        raise LedgerError("I can't find that expense.")
    summary = {"receivables_removed": ZERO, "credits_kept": {}, "voucher_restored": ZERO, "claim_left": None}
    for r in repo.find(Receivable, expense_id=expense_id):
        if r.settled > 0:
            summary["credits_kept"][r.person_id] = summary["credits_kept"].get(r.person_id, ZERO) + r.settled
        summary["receivables_removed"] += r.amount - r.settled
        repo.delete(Receivable, r.id)
    for u in repo.find(VoucherUsage, expense_id=expense_id):
        vouchers.restore(repo, u)
        summary["voucher_restored"] += u.amount
    for c in repo.find(Claim, expense_id=expense_id):
        if c.paid_amount > 0:
            summary["claim_left"] = c.paid_amount  # payout stays as an unapplied reimbursement
        else:
            repo.delete(Claim, c.id)
    exp.status = "deleted"
    repo.update(exp)
    audit(repo, now, "delete", "expenses", expense_id)
    return summary


def links_of(repo, expense_id: str) -> dict:
    recs = repo.find(Receivable, expense_id=expense_id)
    return {
        "receivables": recs,
        "repaid": sum((r.settled for r in recs), ZERO),
        "vouchers": repo.find(VoucherUsage, expense_id=expense_id),
        "claims": repo.find(Claim, expense_id=expense_id),
    }


def last_expense(repo) -> Optional[Expense]:
    exps = active_expenses(repo)
    return max(exps, key=lambda e: (e.created_at or datetime.min, e.id)) if exps else None


def recompute_split(repo, now: datetime, expense_id: str, new_amount: Decimal,
                    new_custom: Optional[dict[str, Decimal]] = None) -> Expense:
    """Change the amount of a (possibly split) expense and recalculate shares by the original mode."""
    exp = repo.get(Expense, expense_id)
    if exp is None:
        raise LedgerError("I can't find that expense.")
    recs = repo.find(Receivable, expense_id=expense_id)
    if exp.split_mode == "custom" and new_custom is None and recs:
        raise LedgerError("This is a custom split. Please give the new shares.")
    inp = ExpenseInput(amount=new_amount, category_id=exp.category_id, bucket=exp.bucket,
                       payments=[Payment(exp.payments[0].account_id, new_amount)], spend_date=exp.spend_date,
                       people=exp.people, split_mode=exp.split_mode, split_values=new_custom or {})
    mine, others = compute_shares(inp)
    by_person = {r.person_id: r for r in recs}
    for pid, share in others.items():
        r = by_person.get(pid)
        if r:
            r.amount = share
            r.status = "settled" if r.settled >= share else "open"
            repo.update(r)
    exp.amount, exp.my_share = new_amount, mine
    exp.payments = [Payment(exp.payments[0].account_id, new_amount)]
    repo.update(exp)
    audit(repo, now, "edit", "expenses", exp.id, f"amount -> {new_amount}")
    return exp
