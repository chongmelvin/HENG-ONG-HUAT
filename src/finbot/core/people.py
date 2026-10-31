"""People and the 'spent with' ranking (PRD 4.4).

Spent with = YOUR SHARE of every entry a person appears on, counted in full for
each person present. Totals overlap by design. Outings = distinct days.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from ..domain.enums import ACTIVE, Relationship
from ..domain.models import Expense, Person, Receivable
from ..domain.money import ZERO
from .audit import audit
from .ids import new_id
from .ledger import LedgerError, active_expenses
from .lookup import find_person

OTHER_FRIENDS = "Other friends"
OTHER_FAMILY = "Other family"


@dataclass
class WithStats:
    person_id: str
    name: str
    relationship: str
    spent: Decimal = ZERO
    days: set = field(default_factory=set)
    places: dict[str, int] = field(default_factory=dict)

    @property
    def outings(self) -> int:
        return len(self.days)

    @property
    def average(self) -> Decimal:
        return (self.spent / self.outings).quantize(Decimal("0.01")) if self.outings else ZERO


def add_person(repo, now, name: str, relationship: Relationship, aliases: Optional[list[str]] = None) -> Person:
    name = name.strip()
    if not name or any(ch.isdigit() for ch in name) and sum(ch.isdigit() for ch in name) >= 5:
        raise LedgerError("Names only, please. I don't store phone numbers or contact details.")
    if find_person(repo, name, include_archived=True):
        raise LedgerError(f"{name} already exists.")
    p = Person(id=new_id("pe"), name=name.title() if name.islower() else name, relationship=relationship, aliases=aliases or [])
    repo.add(p)
    audit(repo, now, "create", "people", p.id, name)
    return p


def ensure_group_person(repo, now, relationship: Relationship) -> Person:
    """`with friends` (unnamed) files under 'Other friends' / 'Other family'."""
    nm = OTHER_FRIENDS if relationship == Relationship.FRIEND else OTHER_FAMILY
    p = find_person(repo, nm, include_archived=True)
    return p or add_person(repo, now, nm, relationship)


def rename_person(repo, now, person_id: str, new_name: str) -> Person:
    p = repo.get(Person, person_id)
    if find_person(repo, new_name) and find_person(repo, new_name).id != person_id:
        raise LedgerError(f"{new_name} already exists.")
    p.name = new_name
    repo.update(p)
    audit(repo, now, "rename", "people", p.id, new_name)
    return p


def merge_people(repo, now, keep_id: str, drop_id: str) -> Person:
    """Combine two names: history, receivables and outings move to `keep`."""
    keep, drop = repo.get(Person, keep_id), repo.get(Person, drop_id)
    if not keep or not drop or keep_id == drop_id:
        raise LedgerError("Pick two different people.")
    for e in repo.all(Expense):
        if drop_id in e.people:
            e.people = list(dict.fromkeys(keep_id if p == drop_id else p for p in e.people))
            repo.update(e)
    for r in repo.find(Receivable, person_id=drop_id):
        r.person_id = keep_id
        repo.update(r)
    from ..domain.models import Settlement
    for s in repo.find(Settlement, person_id=drop_id):
        s.person_id = keep_id
        repo.update(s)
    drop.status = "archived"
    repo.update(drop)
    audit(repo, now, "merge", "people", keep_id, f"{drop.name} -> {keep.name}")
    return keep


def archive_person(repo, now, person_id: str) -> None:
    p = repo.get(Person, person_id)
    p.status = "archived"
    repo.update(p)
    audit(repo, now, "archive", "people", person_id)


def stats(repo, *, start: date, end: date) -> dict[str, WithStats]:
    people = {p.id: p for p in repo.all(Person)}
    out: dict[str, WithStats] = {}
    for e in active_expenses(repo):
        if not (start <= e.spend_date <= end):
            continue
        for pid in e.people:
            p = people.get(pid)
            if not p:
                continue
            s = out.setdefault(pid, WithStats(pid, p.name, p.relationship.value))
            s.spent += e.my_share
            s.days.add(e.spend_date)
            if e.location:
                s.places[e.location] = s.places.get(e.location, 0) + 1
    return out


def ranking(repo, *, start: date, end: date, limit: int = 10) -> list[WithStats]:
    """Rank by spent-with, ties broken by outings then name."""
    items = list(stats(repo, start=start, end=end).values())
    items.sort(key=lambda s: (-s.spent, -s.outings, s.name))
    return items[:limit]


def group_totals(repo, *, start: date, end: date, net_of) -> dict[str, Decimal]:
    """Alone / Friends / Family by net spend. Exclusive groups; they add up to total net spend."""
    people = {p.id: p for p in repo.all(Person)}
    out = defaultdict(lambda: ZERO)
    for e in active_expenses(repo):
        if not (start <= e.spend_date <= end):
            continue
        rels = {people[p].relationship for p in e.people if p in people}
        if not rels:
            g = "Alone"
        elif rels == {Relationship.FRIEND}:
            g = "Friends"
        elif rels == {Relationship.FAMILY}:
            g = "Family"
        else:
            g = "Friends and family"
        out[g] += net_of(e)
    return dict(out)
