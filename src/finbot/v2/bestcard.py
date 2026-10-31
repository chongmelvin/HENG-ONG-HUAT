"""Best card for the next purchase (PRD 6.4).

Earn rules are YOURS to maintain (each has last_verified); the bot never recites card terms from
memory. Models: per-category rate, monthly cap, minimum spend, channel and FX. Anything more
complex belongs in the rule's free-text notes, not in a calculation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from ..core.ledger import active_expenses
from ..core.lookup import norm
from ..core.budgets import month_bounds
from ..domain.enums import ACTIVE, RewardType
from ..domain.models import Card, CardRule, Category, Expense, MerchantMap
from ..domain.money import ZERO

CATEGORY_MAP = {"food": "dining", "transport": "transport", "groceries": "groceries", "shopping": "online", "travel": "overseas"}
STALE_DAYS = 183


def classify(repo, text: str, *, category_name: str = "", overseas: bool = False) -> str:
    """Merchant keyword -> card category (your saved mappings first, then your own category names)."""
    if overseas:
        return "overseas"
    t = norm(text)
    for m in repo.all(MerchantMap):
        if norm(m.keyword) in t:
            return m.card_category
    return CATEGORY_MAP.get(category_name.lower(), "general")


def _expense_class(repo, e: Expense, cats: dict[str, str]) -> str:
    return classify(repo, e.description, category_name=cats.get(e.category_id, ""), overseas=e.currency != "SGD")


def month_card_spend(repo, card: Card, on: date, only_class: Optional[str] = None) -> Decimal:
    s, e = month_bounds(on.year, on.month)
    cats = {c.id: c.name for c in repo.all(Category)}
    total = ZERO
    for ex in active_expenses(repo):
        if s <= ex.spend_date <= e:
            amt = sum((p.amount for p in ex.payments if p.account_id == card.account_id), ZERO)
            if amt and (only_class is None or _expense_class(repo, ex, cats) == only_class):
                total += amt
    return total


@dataclass
class Option:
    card: Card
    rate: Decimal
    value: Decimal          # in S$
    reason: str
    stale: bool = False
    rule: Optional[CardRule] = None


def _value(card: Card, rate: Decimal, amount: Decimal) -> Decimal:
    if card.reward_type == RewardType.CASHBACK:
        return (rate * amount).quantize(Decimal("0.01"))
    return (rate * amount * card.value_per_unit).quantize(Decimal("0.01"))


def _fmt_rate(card: Card, rate: Decimal) -> str:
    return f"{rate * 100:.1f}% cashback" if card.reward_type == RewardType.CASHBACK else f"{rate:g} {card.reward_type.value}/S$"


def evaluate(repo, card: Card, category: str, amount: Decimal, on: date, channel: str = "") -> Optional[Option]:
    rules = [r for r in repo.find(CardRule, card_id=card.id) if r.category in (category, "general")]
    if not rules:
        return None
    rule = next((r for r in rules if r.category == category), rules[0])
    stale = bool(rule.last_verified and (on - rule.last_verified).days > STALE_DAYS)
    rate, why = rule.rate, f"{_fmt_rate(card, rule.rate)} on {category}"
    if rule.channel and channel and rule.channel != channel:
        rate, why = rule.fallback_rate, f"{rule.channel} only; {channel} earns {_fmt_rate(card, rule.fallback_rate)}"
    elif rule.cap is not None:
        used = month_card_spend(repo, card, on, only_class=rule.category)
        if used >= rule.cap:
            rate, why = rule.fallback_rate, f"cap used up (S${used:,.0f} of S${rule.cap:,.0f}); falls back to {_fmt_rate(card, rule.fallback_rate)}"
        else:
            why += f", cap used S${used:,.0f} of S${rule.cap:,.0f}"
    if rule.min_spend is not None and rate == rule.rate:
        spent = month_card_spend(repo, card, on) + amount
        if spent < rule.min_spend:
            rate, why = rule.fallback_rate, f"needs S${rule.min_spend - spent:,.0f} more spend this month to unlock {_fmt_rate(card, rule.rate)}"
    return Option(card, rate, _value(card, rate, amount), why, stale, rule)


def recommend(repo, text: str, amount: Decimal, on: date, *, channel: str = "", overseas: bool = False,
              category_name: str = "", top: int = 3) -> tuple[str, list[Option]]:
    cat = classify(repo, text, category_name=category_name, overseas=overseas)
    opts = [o for c in repo.find(Card, status=ACTIVE) if (o := evaluate(repo, c, cat, amount, on, channel))]
    opts.sort(key=lambda o: -o.value)
    return cat, opts[:top]
