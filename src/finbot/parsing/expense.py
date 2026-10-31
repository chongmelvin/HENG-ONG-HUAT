"""Free-text expense parser (PRD 4.2).

    chicken rice 5.50 paylah
    grab 12 cc with bob orchard
    y dinner 120 cc split bob alice          (yesterday, equal split)
    dinner 120 cc bob 30 alice 40            (custom split)
    lunch 12 voucher cdc 8 paynow 4          (split payment)
    taxi 25 cc #claim acme
    ramen 1200 yen sgd 11.40 cash            (foreign amount plus the SGD actually spent)

The parser never guesses silently: anything it cannot resolve is returned as a question
for the engine to ask (unknown account, unknown person, two amounts, no amount...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..domain.enums import Relationship
from ..domain.models import Account, Category, Person, Settings
from ..core.lookup import find_account, find_category, find_person, norm, suggest_person
from .dates import DateError, MONTHS, future_fix, parse_day_month, relative

CURRENCIES = {"yen": "JPY", "jpy": "JPY", "usd": "USD", "krw": "KRW", "won": "KRW", "thb": "THB", "baht": "THB",
              "myr": "MYR", "rm": "MYR", "eur": "EUR", "gbp": "GBP", "idr": "IDR", "aud": "AUD", "cny": "CNY",
              "hkd": "HKD", "vnd": "VND", "twd": "TWD", "sgd": "SGD"}
NUM = re.compile(r"^(?:s?\$)?(\d[\d,]*(?:\.\d+)?)$", re.I)
PCT = re.compile(r"^(\d+(?:\.\d+)?)%$")


@dataclass
class Parsed:
    raw: str
    amount: Optional[Decimal] = None
    ambiguous_amounts: list[Decimal] = field(default_factory=list)
    description: str = ""
    category: Optional[Category] = None
    unknown_words: list[str] = field(default_factory=list)       # candidate words for a new alias
    account: Optional[Account] = None
    unknown_account: Optional[str] = None
    payments: list[tuple[Account, Decimal]] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    unknown_people: list[str] = field(default_factory=list)
    person_suggestion: Optional[Person] = None
    unnamed: list[Relationship] = field(default_factory=list)
    location: str = ""
    tags: list[str] = field(default_factory=list)
    spend_date: Optional[date] = None
    date_error: str = ""
    date_suggestion: Optional[date] = None
    split_mode: str = ""
    split_values: dict[str, Decimal] = field(default_factory=dict)  # person.id -> amount or percent
    claimable: bool = False
    claimant: str = ""
    big: bool = False
    currency: str = ""                    # foreign currency code, if any
    foreign_amount: Optional[Decimal] = None
    home_amount: Optional[Decimal] = None
    refund: bool = False
    income: bool = False

    @property
    def needs(self) -> list[str]:
        out = []
        if self.date_error:
            out.append("date")
        if self.ambiguous_amounts:
            out.append("ambiguous_amount")
        elif self.amount is None and self.home_amount is None:
            out.append("amount")
        if self.unknown_people:
            out.append("person")
        if self.unknown_account:
            out.append("account")
        if self.category is None:
            out.append("category")
        if self.account is None and not self.payments and not self.unknown_account:
            out.append("account_default")
        return out


def _num(tok: str) -> Optional[Decimal]:
    m = NUM.match(tok)
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _tokens(text: str) -> list[str]:
    text = text.replace("@", " @")
    return [t for t in re.split(r"\s+", text.strip()) if t]


def parse_expense(repo, settings: Settings, text: str, today: date, *, trip_currency: str = "") -> Parsed:
    p = Parsed(raw=text)
    toks = _tokens(text)
    low = [t.lower() for t in toks]
    used = [False] * len(toks)

    # ---- date ------------------------------------------------------------
    for i, t in enumerate(low):
        d = relative(t, today)
        if d and (i == 0 or i == len(low) - 1):
            p.spend_date, used[i] = d, True
            break
        if i + 1 < len(low) and re.fullmatch(r"\d{1,2}", t) and low[i + 1] in MONTHS:
            year = None
            if i + 2 < len(low) and re.fullmatch(r"20\d\d", low[i + 2]):
                year = int(low[i + 2])
                used[i + 2] = True
            try:
                p.spend_date = parse_day_month(int(t), MONTHS[low[i + 1]], year, today)
            except DateError:
                p.date_error = f"I couldn't read \"{t} {low[i+1]}\" as a date. Try y, -2d, or 12 oct."
            used[i] = used[i + 1] = True
            break
    if p.spend_date and p.spend_date > today:
        p.date_suggestion = future_fix(p.spend_date, today)
        p.date_error = f"{p.spend_date:%-d %b} is in the future."
    p.spend_date = p.spend_date or today

    # ---- tags / flags ----------------------------------------------------
    for i, t in enumerate(low):
        if t.startswith("#"):
            used[i] = True
            tag = t[1:]
            if tag == "claim":
                p.claimable = True
                p.tags.append("Claim")
                if i + 1 < len(toks) and not toks[i + 1].startswith("#") and _num(toks[i + 1]) is None:
                    p.claimant, used[i + 1] = toks[i + 1].title(), True
            elif tag == "big":
                p.big = True
                p.tags.append("Big-ticket")
            else:
                p.tags.append(tag.title())

    # ---- amounts (first number that is not part of a date) -------------------
    nums = [(i, _num(t)) for i, t in enumerate(toks) if not used[i] and _num(t) is not None]
    if nums:
        # two numbers in a row (no word between) = ambiguous total
        first = nums[0][0]
        run = [nums[0]]
        for i, v in nums[1:]:
            if i == run[-1][0] + 1:
                run.append((i, v))
            else:
                break
        if len(run) > 1 and not (len(toks) > run[-1][0] + 1 and low[run[-1][0] + 1] in CURRENCIES):
            p.ambiguous_amounts = [v for _, v in run]
        total_i, total = nums[0]
        p.amount = total
        used[total_i] = True
    else:
        total_i = -1

    # ---- currency: "1200 yen sgd 11.40" ----------------------------------------
    i = total_i + 1
    if total_i >= 0 and i < len(low) and low[i] in CURRENCIES and low[i] != "sgd":
        p.currency, p.foreign_amount, used[i] = CURRENCIES[low[i]], p.amount, True
        if i + 2 < len(low) and low[i + 1] == "sgd" and _num(toks[i + 2]) is not None:
            p.home_amount = _num(toks[i + 2])
            used[i + 1] = used[i + 2] = True
    elif total_i >= 0 and i + 1 < len(low) and low[i] == "sgd" and _num(toks[i + 1]) is not None:
        used[i] = used[i + 1] = True            # "ramen sgd 11.40": explicit home amount during a trip
        p.home_amount, p.amount = _num(toks[i + 1]), _num(toks[i + 1])
    elif trip_currency and trip_currency != "SGD" and p.amount is not None:
        p.currency, p.foreign_amount = trip_currency, p.amount   # trip mode: bare amount is local currency

    # ---- keywords: with / split / treat ------------------------------------
    mode_idx = None
    for i, t in enumerate(low):
        if used[i]:
            continue
        if t in ("split", "treat"):
            p.split_mode = "equal" if t == "split" else "treat"
            used[i], mode_idx = True, i
        if t == "voucher":
            used[i] = True

    def take_people(start: int) -> None:
        j = start
        while j < len(toks) and not used[j]:
            name = toks[j].lstrip("@")
            nl = name.lower()
            if nl in ("friends", "friend"):
                p.unnamed.append(Relationship.FRIEND)
            elif nl in ("family", "fam"):
                p.unnamed.append(Relationship.FAMILY)
            else:
                person = find_person(repo, name)
                if person:
                    if person not in p.people:
                        p.people.append(person)
                elif j == start or toks[j].startswith("@"):
                    sug = suggest_person(repo, name)
                    if sug and not p.person_suggestion:
                        p.person_suggestion = sug
                    p.unknown_people.append(name)
                else:
                    return
            used[j] = True
            j += 1

    for i, t in enumerate(low):
        if used[i]:
            continue
        if t == "with":
            used[i] = True
            take_people(i + 1)
        elif toks[i].startswith("@"):
            take_people(i)
    if mode_idx is not None:
        take_people(mode_idx + 1)

    # ---- accounts, custom splits, split payments ---------------------------------
    i = 0
    n_after = total_i + 1 if total_i >= 0 else 0
    pay_pairs: list[tuple[Account, Decimal]] = []
    while i < len(toks):
        if used[i] or i < n_after - 1 and total_i >= 0 and i < total_i:
            i += 1
            continue
        acct = None
        span = 1
        for L in (3, 2, 1):
            cand = " ".join(low[i:i + L])
            acct = find_account(repo, cand) if i + L <= len(toks) else None
            if acct:
                span = L
                break
        person = find_person(repo, toks[i].lstrip("@")) if not acct else None
        nxt = i + span
        nxt_num = _num(toks[nxt]) if nxt < len(toks) and not used[nxt] else None
        pct = PCT.match(low[nxt]) if nxt < len(toks) and not used[nxt] else None
        if acct and nxt_num is not None and total_i >= 0 and i > total_i:
            pay_pairs.append((acct, nxt_num))
            for k in range(i, nxt + 1):
                used[k] = True
            i = nxt + 1
            continue
        if acct:
            if p.account is None:
                p.account = acct
            for k in range(i, i + span):
                used[k] = True
            i += span
            continue
        if person and nxt_num is not None and i > total_i:
            p.split_mode, p.split_values[person.id] = "custom", nxt_num
            if person not in p.people:
                p.people.append(person)
            used[i] = used[nxt] = True
            i = nxt + 1
            continue
        if person and pct:
            p.split_mode, p.split_values[person.id] = "percent", Decimal(pct.group(1))
            if person not in p.people:
                p.people.append(person)
            used[i] = used[nxt] = True
            i = nxt + 1
            continue
        i += 1
    if len(pay_pairs) >= 2 or (pay_pairs and p.account is None and p.amount is not None and sum(v for _, v in pay_pairs) == p.amount):
        p.payments = pay_pairs
    elif pay_pairs:
        p.account = pay_pairs[0][0]
    if p.split_mode == "equal" and not p.people:
        p.split_mode = ""

    # ---- places -------------------------------------------------------------
    joined = {norm(pl): pl for pl in settings.places}
    for i in range(len(toks)):
        for L in (2, 1):
            if i + L > len(toks):
                continue
            cand = norm(" ".join(toks[i:i + L]))
            if cand in joined and not any(used[i:i + L]):
                p.location = joined[cand]
                for k in range(i, i + L):
                    used[k] = True
                break

    # ---- unknown account: first leftover word after the amount -----------------------
    if p.account is None and not p.payments and total_i >= 0:
        for i in range(total_i + 1, len(toks)):
            if not used[i] and not toks[i].startswith("#") and _num(toks[i]) is None:
                p.unknown_account = toks[i]
                used[i] = True
                break

    # ---- description & category -----------------------------------------------
    words = [toks[i] for i in range(len(toks)) if not used[i] and _num(toks[i]) is None]
    p.description = " ".join(words)
    for w in words:
        c = find_category(repo, w)
        if c:
            p.category = c
            break
    if p.category is None:
        c = find_category(repo, p.description)
        p.category = c
    if p.category is None:
        p.unknown_words = [norm(p.description)] if p.description else []
    return p
