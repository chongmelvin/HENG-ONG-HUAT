"""Domain entities. Every entity is a dataclass tied to one Sheet tab (__table__)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from .enums import (ACTIVE, AccountType, AssetGroup, Bucket, ClaimStatus, HoldingType,
                    Persona, Relationship, RewardType)
from .money import ZERO


def entity(table: str):
    def deco(cls):
        cls = dataclass(cls)
        cls.__table__ = table
        return cls
    return deco


# ---- nested value objects (stored as JSON inside a cell) -------------------
@dataclass
class Payment:
    account_id: str
    amount: Decimal


@dataclass
class Alloc:
    receivable_id: str
    amount: Decimal


@dataclass
class Balance:
    account_id: str
    amount: Decimal


# ---- configuration ----------------------------------------------------------
@entity("categories")
class Category:
    id: str
    name: str
    default_bucket: Bucket = Bucket.MONTHLY
    ask_me: bool = False
    exempt_scold: bool = False
    aliases: list[str] = field(default_factory=list)
    status: str = ACTIVE


@entity("limits")
class BudgetLimit:
    id: str
    scope: str  # "category:<id>" | "total_monthly" | "total_yearly"
    amount: Decimal
    effective_from: date


@entity("accounts")
class Account:
    id: str
    name: str
    type: AccountType
    currency: str = "SGD"
    opening_balance: Decimal = ZERO
    asset_group: AssetGroup = AssetGroup.FIXED
    aliases: list[str] = field(default_factory=list)
    status: str = ACTIVE

    @property
    def is_liability(self) -> bool:
        return self.type == AccountType.CREDIT_CARD


@entity("people")
class Person:
    id: str
    name: str
    relationship: Relationship = Relationship.FRIEND
    aliases: list[str] = field(default_factory=list)
    status: str = ACTIVE


@entity("settings")
class Settings:
    id: str = "main"
    timezone: str = "Asia/Singapore"
    currency: str = "SGD"
    report_hour: int = 9
    persona: Persona = Persona.LIGHT
    indicators: bool = True
    pin_hash: str = ""
    pin_salt: str = ""
    large_amount: Decimal = Decimal("5000.00")
    dup_window_s: int = 120
    big_ticket_threshold: Decimal = Decimal("100.00")
    big_ticket_prompt: bool = True
    chase_days: int = 7
    default_lead_days: int = 3
    savings_green: int = 30
    savings_yellow: int = 15
    hidden_sections: list[str] = field(default_factory=list)
    setup_complete: bool = False
    first_snapshot_date: Optional[date] = None
    active_trip_id: str = ""
    places: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


# ---- transactions -----------------------------------------------------------
@entity("expenses")
class Expense:
    id: str
    amount: Decimal                      # total you paid
    category_id: str
    bucket: Bucket
    payments: list[Payment]
    spend_date: date
    entry_date: date
    my_share: Decimal = ZERO
    currency: str = "SGD"
    foreign_amount: Optional[Decimal] = None
    fx_rate: Optional[Decimal] = None
    description: str = ""
    tags: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    location: str = ""
    split_mode: str = ""                 # "", equal, custom, percent, treat
    claimable: bool = False
    trip_id: str = ""
    item: str = ""
    note: str = ""
    idem_key: str = ""
    status: str = ACTIVE                 # active | deleted
    created_at: Optional[datetime] = None

    @property
    def account_id(self) -> str:
        return self.payments[0].account_id if self.payments else ""


@entity("incomes")
class Income:
    id: str
    amount: Decimal
    source: str
    account_id: str
    date: date
    recurring: bool = False
    gross: Optional[Decimal] = None
    bonus: Optional[Decimal] = None
    deductions: Optional[Decimal] = None
    note: str = ""
    status: str = ACTIVE


@entity("transfers")
class Transfer:
    id: str
    from_account: str
    to_account: str
    amount: Decimal
    date: date
    note: str = ""
    status: str = ACTIVE


@entity("adjustments")
class Adjustment:
    id: str
    account_id: str
    amount: Decimal
    reason: str
    date: date


@entity("refunds")
class Refund:
    id: str
    amount: Decimal
    account_id: str
    date: date
    expense_id: str = ""
    category_id: str = ""
    note: str = ""
    status: str = ACTIVE


# ---- people and debts -------------------------------------------------------
@entity("receivables")
class Receivable:
    id: str
    expense_id: str
    person_id: str
    amount: Decimal
    created: date
    settled: Decimal = ZERO
    status: str = "open"                 # open | settled | written_off

    @property
    def outstanding(self) -> Decimal:
        return ZERO if self.status != "open" else self.amount - self.settled


@entity("settlements")
class Settlement:
    id: str
    person_id: str
    amount: Decimal
    account_id: str
    date: date
    applied: list[Alloc] = field(default_factory=list)
    credit: Decimal = ZERO               # overpayment kept as a credit you owe the person


@entity("claims")
class Claim:
    id: str
    expense_id: str
    claimant: str
    amount: Decimal
    status: ClaimStatus = ClaimStatus.UNCLAIMED
    ref: str = ""
    batch: str = ""
    submitted: Optional[date] = None
    paid_amount: Decimal = ZERO
    paid_date: Optional[date] = None
    account_id: str = ""

    @property
    def outstanding(self) -> Decimal:
        if self.status == ClaimStatus.REJECTED:
            return ZERO
        return max(self.amount - self.paid_amount, ZERO)


# ---- obligations ------------------------------------------------------------
@entity("bills")
class Bill:
    id: str
    name: str
    due_day: int
    amount: Decimal = ZERO
    last_amount: Decimal = ZERO
    variable: bool = False
    category_id: str = ""
    account_id: str = ""
    recurrence: str = "monthly"          # monthly | quarterly | half_yearly | yearly
    anchor_month: int = 1                # first month the bill falls in (non-monthly)
    lead_days: int = 3
    kind: str = "bill"                   # bill | insurance | subscription | loan
    ref_id: str = ""
    is_transfer: bool = False            # e.g. credit card payment
    last_paid: Optional[date] = None
    paid_on: Optional[date] = None
    snooze_until: Optional[date] = None
    created: Optional[date] = None
    status: str = ACTIVE


@entity("cards")
class Card:
    id: str
    account_id: str
    bank: str
    name: str
    last4: str
    statement_day: int
    due_day: int
    limit: Decimal = ZERO
    annual_fee: Decimal = ZERO
    fee_month: int = 0
    reward_type: RewardType = RewardType.MILES
    value_per_unit: Decimal = ZERO
    status: str = ACTIVE


@entity("insurance")
class Insurance:
    id: str
    insurer: str
    product: str
    type: str
    premium: Decimal
    frequency: str                       # monthly | quarterly | half_yearly | yearly
    next_due: date
    insured: str = "me"
    coverage_notes: str = ""
    pay_account_id: str = ""
    start: Optional[date] = None
    end: Optional[date] = None
    cash_value: Optional[Decimal] = None
    beneficiary: str = ""
    policy_last4: str = ""
    status: str = ACTIVE


# ---- perks ------------------------------------------------------------------
@entity("vouchers")
class Voucher:
    id: str
    scheme: str
    original: Decimal
    remaining: Decimal
    expires: date
    label: str = ""
    issued: Optional[date] = None
    format: str = "digital"
    eligible_use: str = ""
    status: str = "active"               # active | used | expired
    last_verified: Optional[date] = None


@entity("voucher_usage")
class VoucherUsage:
    id: str
    voucher_id: str
    expense_id: str
    amount: Decimal
    date: date


@entity("items")
class Item:
    id: str
    name: str
    price: Decimal
    purchase_date: date
    expense_id: str = ""
    brand: str = ""
    warranty_months: int = 0
    warranty_end: Optional[date] = None
    serial: str = ""
    status: str = "in_use"               # in_use | sold | disposed
    sale_price: Optional[Decimal] = None
    receipt_link: str = ""
    file_id: str = ""


# ---- net worth --------------------------------------------------------------
@entity("snapshots")
class Snapshot:
    id: str
    date: date
    balances: list[Balance]
    owed: Decimal = ZERO
    variable: Decimal = ZERO
    fixed: Decimal = ZERO
    net_worth: Decimal = ZERO
    gap: Decimal = ZERO
    written_off: Decimal = ZERO


@entity("savings_buckets")
class SavingsBucket:
    id: str
    name: str
    target: Decimal = ZERO
    target_date: Optional[date] = None
    status: str = ACTIVE


@entity("allocations")
class Allocation:
    id: str
    bucket_id: str
    amount: Decimal
    date: date
    note: str = ""


# ---- v2 ---------------------------------------------------------------------
@entity("holdings")
class Holding:
    id: str
    name: str
    symbol: str
    type: HoldingType
    units: Decimal
    cost_basis: Decimal
    platform: str = ""
    price: Decimal = Decimal("0")
    price_date: Optional[date] = None
    price_source: str = "auto"
    status: str = ACTIVE

    @property
    def value(self) -> Decimal:
        return (self.units * self.price).quantize(Decimal("0.01"))


@entity("prices")
class PricePoint:
    id: str
    holding_id: str
    date: date
    price: Decimal


@entity("trips")
class Trip:
    id: str
    name: str
    start: date
    currency: str = "SGD"
    end: Optional[date] = None
    budget: Optional[Decimal] = None
    active: bool = True
    paused: bool = False
    manual_rate: Optional[Decimal] = None
    last_check: Optional[date] = None


@entity("reward_programs")
class RewardProgram:
    id: str
    name: str
    kind: RewardType
    value_per_unit: Decimal = ZERO
    card_id: str = ""


@entity("reward_balances")
class RewardBalance:
    id: str
    program_id: str
    balance: Decimal
    expires: Optional[date] = None
    last_confirmed: Optional[date] = None


@entity("reward_events")
class RewardEvent:
    id: str
    program_id: str
    date: date
    kind: str                            # earn | redeem | transfer | expire | adjust
    amount: Decimal
    source: str = "estimated"            # estimated | confirmed
    note: str = ""


@entity("card_rules")
class CardRule:
    id: str
    card_id: str
    category: str                        # dining | online | transport | groceries | overseas | general
    rate: Decimal                        # miles per S$ or cashback fraction (0.05 = 5%)
    cap: Optional[Decimal] = None        # monthly S$ spend cap for the bonus rate
    min_spend: Optional[Decimal] = None  # monthly minimum spend to unlock the rate
    channel: str = ""                    # "" any | online | contactless | in_app
    fallback_rate: Decimal = Decimal("0.4")
    last_verified: Optional[date] = None
    notes: str = ""


@entity("merchant_map")
class MerchantMap:
    id: str
    keyword: str
    card_category: str


@entity("subscriptions")
class Subscription:
    id: str
    name: str
    amount: Decimal
    cycle: str = "monthly"               # monthly | yearly
    next_renewal: Optional[date] = None
    account_id: str = ""
    trial_end: Optional[date] = None
    merchant: str = ""
    status: str = ACTIVE


@entity("loans")
class Loan:
    id: str
    lender: str
    original: Decimal
    balance: Decimal
    rate: Decimal                        # annual rate as a fraction, 0.04 = 4%
    instalment: Decimal
    pay_day: int = 1
    status: str = ACTIVE


@entity("annual_items")
class AnnualItem:
    id: str
    name: str
    amount: Decimal
    month: int
    savings_bucket_id: str = ""


# ---- process ----------------------------------------------------------------
@entity("pending")
class Pending:
    id: str
    kind: str
    payload: dict = field(default_factory=dict)
    created: Optional[datetime] = None


@entity("setup_state")
class SetupState:
    id: str = "main"
    module: str = ""
    step: int = 0
    answers: dict = field(default_factory=dict)
    done: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    started: Optional[datetime] = None


@entity("review_sessions")
class ReviewSession:
    id: str
    month: str
    step: int = 1
    done: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)


@entity("audit")
class AuditEntry:
    id: str
    at: datetime
    action: str
    table: str
    record_id: str = ""
    detail: str = ""


@entity("processed")
class Processed:
    id: str
    at: Optional[datetime] = None


ALL_ENTITIES = [
    Category, BudgetLimit, Account, Person, Settings, Expense, Income, Transfer, Adjustment, Refund,
    Receivable, Settlement, Claim, Bill, Card, Insurance, Voucher, VoucherUsage, Item, Snapshot,
    SavingsBucket, Allocation, Holding, PricePoint, Trip, RewardProgram, RewardBalance, RewardEvent,
    CardRule, MerchantMap, Subscription, Loan, AnnualItem, Pending, SetupState, ReviewSession,
    AuditEntry, Processed,
]
