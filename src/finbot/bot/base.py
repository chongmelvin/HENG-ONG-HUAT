"""Shared plumbing for the engine mixins."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from ..clock import Clock
from ..core.audit import audit
from ..core.ids import new_id
from ..core.indicators import Badge
from ..core.pin import PinGate
from ..domain.models import Account, Category, Pending, Person, Settings
from ..messaging.templates import Messenger
from .types import Button, Reply


class Base:
    def __init__(self, repo, clock: Clock, *, fx=None, prices=None, llm=None, gate: Optional[PinGate] = None, seed=None) -> None:
        self.repo, self.clock, self.fx, self.prices, self.llm = repo, clock, fx, prices, llm
        self.gate = gate or PinGate()
        self._seed = seed
        self._messenger: Optional[Messenger] = None

    # ---- settings and time
    def settings(self) -> Settings:
        s = self.repo.get(Settings, "main")
        if s is None:
            s = self.repo.add(Settings())
        return s

    def save_settings(self, s: Settings) -> None:
        self.repo.update(s)

    def now(self) -> datetime:
        return self.clock.now()

    def today(self) -> date:
        return self.clock.today()

    @property
    def msg(self) -> Messenger:
        s = self.settings()
        if self._messenger is None:
            self._messenger = Messenger(s, self._seed)
        self._messenger.settings = s
        return self._messenger

    def badge(self) -> Badge:
        return Badge.of(self.settings())

    # ---- pending actions (button callbacks and awaited text)
    def pend(self, kind: str, payload: dict, *, awaiting_text: bool = False) -> Pending:
        if awaiting_text:
            for p in self.repo.all(Pending):
                if p.payload.get("_await"):
                    self.repo.delete(Pending, p.id)
        payload = {**payload, "_await": awaiting_text}
        return self.repo.add(Pending(id=new_id("pd"), kind=kind, payload=payload, created=self.now()))

    def awaiting(self) -> Optional[Pending]:
        ps = [p for p in self.repo.all(Pending) if p.payload.get("_await")]
        return max(ps, key=lambda p: p.created) if ps else None

    def drop(self, p: Pending | str) -> None:
        self.repo.delete(Pending, p if isinstance(p, str) else p.id)

    def cb(self, p: Pending, action: str, arg: str = "") -> str:
        return f"p:{p.id}:{action}" + (f":{arg}" if arg else "")

    def buttons(self, p: Pending, *rows_: list[tuple[str, str, str]]) -> list[list[Button]]:
        """rows of (label, action, arg)."""
        return [[Button(l, self.cb(p, a, g)) for l, a, g in r] for r in rows_]

    # ---- name helpers
    def cat_name(self, cid: str) -> str:
        c = self.repo.get(Category, cid)
        return c.name if c else "?"

    def acct_name(self, aid: str) -> str:
        a = self.repo.get(Account, aid)
        return a.name if a else "?"

    def person_name(self, pid: str) -> str:
        p = self.repo.get(Person, pid)
        return p.name if p else "?"

    def plain(self, text: str) -> Reply:
        return Reply(text)

    def audit(self, action: str, table: str, rid: str = "", detail: str = "") -> None:
        audit(self.repo, self.now(), action, table, rid, detail)
