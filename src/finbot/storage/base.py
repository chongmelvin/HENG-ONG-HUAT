"""Repository abstraction. Services only depend on this, never on Sheets."""
from __future__ import annotations

import copy
import dataclasses
from typing import Callable, Iterable, Optional, Protocol, TypeVar

T = TypeVar("T")


class NotFound(KeyError):
    pass


class Repo(Protocol):
    def add(self, obj: T) -> T: ...
    def get(self, cls: type[T], id: str) -> Optional[T]: ...
    def all(self, cls: type[T]) -> list[T]: ...
    def find(self, cls: type[T], pred: Optional[Callable[[T], bool]] = None, **eq) -> list[T]: ...
    def update(self, obj: T) -> T: ...
    def delete(self, cls: type[T], id: str) -> None: ...


class MemoryRepo:
    """In-memory repository used by tests and local dev. Mirrors SheetsRepo semantics."""

    def __init__(self) -> None:
        self._t: dict[str, dict[str, object]] = {}

    def _tab(self, cls) -> dict[str, object]:
        return self._t.setdefault(cls.__table__, {})

    def add(self, obj):
        tab = self._tab(type(obj))
        if obj.id in tab:
            raise ValueError(f"duplicate id {obj.id} in {type(obj).__table__}")
        tab[obj.id] = copy.deepcopy(obj)
        return obj

    def get(self, cls, id):
        o = self._tab(cls).get(id)
        return copy.deepcopy(o) if o is not None else None

    def all(self, cls):
        return [copy.deepcopy(o) for o in self._tab(cls).values()]

    def find(self, cls, pred=None, **eq):
        out = []
        for o in self._tab(cls).values():
            if all(getattr(o, k) == v for k, v in eq.items()) and (pred is None or pred(o)):
                out.append(copy.deepcopy(o))
        return out

    def update(self, obj):
        tab = self._tab(type(obj))
        if obj.id not in tab:
            raise NotFound(obj.id)
        tab[obj.id] = copy.deepcopy(obj)
        return obj

    def delete(self, cls, id):
        self._tab(cls).pop(id, None)

    def upsert(self, obj):
        tab = self._tab(type(obj))
        tab[obj.id] = copy.deepcopy(obj)
        return obj
