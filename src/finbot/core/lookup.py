"""Name resolution with aliases, case-insensitive. Used by parsers and settings."""
from __future__ import annotations

import difflib
import re
from typing import Optional

from ..domain.enums import ACTIVE
from ..domain.models import Account, Category, Person


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _match(items, text: str):
    t = norm(text)
    if not t:
        return None
    for it in items:
        names = [it.name, *getattr(it, "aliases", [])]
        if any(norm(n) == t for n in names):
            return it
    return None


def find_category(repo, text: str) -> Optional[Category]:
    return _match([c for c in repo.all(Category) if c.status == ACTIVE], text)


def find_account(repo, text: str) -> Optional[Account]:
    return _match([a for a in repo.all(Account) if a.status == ACTIVE], text)


def find_person(repo, text: str, include_archived: bool = False) -> Optional[Person]:
    people = repo.all(Person) if include_archived else [p for p in repo.all(Person) if p.status == ACTIVE]
    return _match(people, text)


def suggest_person(repo, text: str) -> Optional[Person]:
    people = [p for p in repo.all(Person) if p.status == ACTIVE]
    names = {norm(p.name): p for p in people}
    close = difflib.get_close_matches(norm(text), list(names), n=1, cutoff=0.6)
    return names[close[0]] if close else None


def name_of(repo, cls, id: str, default: str = "?") -> str:
    o = repo.get(cls, id)
    return o.name if o else default
