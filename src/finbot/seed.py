"""Default configuration offered by the setup wizard and used by tests."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .domain.enums import AccountType, AssetGroup, Bucket, Relationship
from .domain.models import Account, Category, Person, Settings
from .core.budgets import TOTAL_M, TOTAL_Y, set_limit
from .core.ids import new_id

DEFAULT_CATEGORIES = [
    # name, bucket, ask_me, exempt, aliases, monthly limit
    ("Food", Bucket.MONTHLY, False, False, ["mcd", "lunch", "dinner", "kopi"], 600),
    ("Groceries", Bucket.MONTHLY, False, False, ["supermarket", "ntuc"], 400),
    ("Transport", Bucket.MONTHLY, False, False, ["grab", "mrt", "bus", "taxi"], 200),
    ("Shopping", Bucket.MONTHLY, True, False, [], 300),
    ("Bills", Bucket.MONTHLY, False, True, [], None),
    ("Fixed", Bucket.MONTHLY, False, True, [], None),
    ("Fun", Bucket.MONTHLY, False, False, ["movie"], None),
    ("Gifts", Bucket.YEARLY, False, False, [], None),
    ("Travel", Bucket.YEARLY, False, False, [], None),
    ("Insurance", Bucket.YEARLY, False, True, [], None),
]

DEFAULT_TAGS = ["Treating", "Social", "Recurring", "Impulse", "Fees", "Subscription", "Big-ticket", "Claim", "Trip"]


def apply_default_categories(repo, now, with_limits: bool = True) -> list[Category]:
    out = []
    for name, bucket, ask, exempt, aliases, lim in DEFAULT_CATEGORIES:
        c = Category(id=new_id("ca"), name=name, default_bucket=bucket, ask_me=ask, exempt_scold=exempt, aliases=aliases)
        repo.add(c)
        out.append(c)
        if with_limits and lim:
            set_limit(repo, now, f"category:{c.id}", Decimal(lim), date(now.year, 1, 1))
    return out


def demo_world(repo, now):
    """A small, realistic setup used by tests and `scripts/seed_demo.py`."""
    settings = Settings()
    repo.add(settings)
    cats = {c.name: c for c in apply_default_categories(repo, now)}
    set_limit(repo, now, TOTAL_M, Decimal("2000"), date(now.year, 1, 1))
    set_limit(repo, now, TOTAL_Y, Decimal("12000"), date(now.year, 1, 1))
    accts = {}
    for name, typ, aliases, grp in [
        ("Cash", AccountType.CASH, [], AssetGroup.FIXED),
        ("PayLah", AccountType.EWALLET, ["paylah"], AssetGroup.FIXED),
        ("PayNow", AccountType.BANK, ["paynow"], AssetGroup.FIXED),
        ("DBS Bank", AccountType.BANK, ["dbs"], AssetGroup.FIXED),
        ("DBS Card", AccountType.CREDIT_CARD, ["cc", "card"], AssetGroup.FIXED),
        ("CDC", AccountType.VOUCHER, ["cdc"], AssetGroup.FIXED),
    ]:
        a = Account(id=new_id("ac"), name=name, type=typ, aliases=aliases, asset_group=grp)
        repo.add(a)
        accts[name] = a
    people = {}
    for name, rel in [("Bob", Relationship.FRIEND), ("Alice", Relationship.FRIEND), ("Mum", Relationship.FAMILY)]:
        p = Person(id=new_id("pe"), name=name, relationship=rel)
        repo.add(p)
        people[name] = p
    return settings, cats, accts, people
