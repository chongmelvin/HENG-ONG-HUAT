"""Google Sheets repository (production storage).

Design notes
- One tab per entity (`Entity.__table__`), header row = dataclass field names.
- All reads are served from an in-process cache loaded once per tab; writes are
  write-through. Google's quota is ~60 writes/min, so writes are queued and
  flushed with exponential backoff on 429/5xx (see `_with_retry`).
- `verify_schema()` runs on startup and refuses to write if someone renamed or
  reordered a header cell, which would silently corrupt data.
- Last write wins; this is a single-user bot.
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Callable, Optional

import gspread
from gspread.exceptions import APIError

from ..domain.models import ALL_ENTITIES
from .codec import columns, from_row, to_row

log = logging.getLogger(__name__)


class SchemaError(RuntimeError):
    pass


class SheetsRepo:
    def __init__(self, spreadsheet: "gspread.Spreadsheet", *, max_retries: int = 6) -> None:
        self._ss = spreadsheet
        self._max_retries = max_retries
        self._lock = threading.RLock()
        self._cache: dict[str, dict[str, object]] = {}
        self._rowno: dict[str, dict[str, int]] = {}
        self._ws: dict[str, "gspread.Worksheet"] = {}

    # ---- construction -----------------------------------------------------
    @classmethod
    def from_service_account(cls, credentials_json: dict, sheet_id: str) -> "SheetsRepo":
        gc = gspread.service_account_from_dict(credentials_json)
        return cls(gc.open_by_key(sheet_id))

    # ---- retry wrapper ----------------------------------------------------
    def _with_retry(self, fn: Callable, *args, **kwargs):
        delay = 1.0
        for attempt in range(self._max_retries):
            try:
                return fn(*args, **kwargs)
            except APIError as e:
                status = getattr(e.response, "status_code", 0)
                if status in (429, 500, 502, 503) and attempt < self._max_retries - 1:
                    log.warning("Sheets %s, retry in %.1fs", status, delay)
                    time.sleep(delay)
                    delay = min(delay * 2, 30)
                    continue
                raise

    # ---- schema -----------------------------------------------------------
    def ensure_tabs(self) -> None:
        existing = {w.title for w in self._ss.worksheets()}
        for cls in ALL_ENTITIES:
            if cls.__table__ not in existing:
                ws = self._with_retry(self._ss.add_worksheet, cls.__table__, rows=500, cols=max(len(columns(cls)), 6))
                self._with_retry(ws.update, "A1", [columns(cls)])

    def verify_schema(self) -> None:
        for cls in ALL_ENTITIES:
            ws = self._worksheet(cls)
            header = self._with_retry(ws.row_values, 1)
            expected = columns(cls)
            if header[: len(expected)] != expected:
                raise SchemaError(
                    f"Tab '{cls.__table__}' header is {header[:len(expected)]}, expected {expected}. "
                    "Fix the header row before the bot writes anything."
                )

    def _worksheet(self, cls):
        t = cls.__table__
        if t not in self._ws:
            self._ws[t] = self._ss.worksheet(t)
        return self._ws[t]

    def _load(self, cls) -> dict[str, object]:
        t = cls.__table__
        with self._lock:
            if t in self._cache:
                return self._cache[t]
            ws = self._worksheet(cls)
            rows = self._with_retry(ws.get_all_values)
            objs: dict[str, object] = {}
            rn: dict[str, int] = {}
            for i, row in enumerate(rows[1:], start=2):
                if not any(row):
                    continue
                o = from_row(cls, row)
                objs[o.id] = o
                rn[o.id] = i
            self._cache[t], self._rowno[t] = objs, rn
            return objs

    # ---- Repo API ---------------------------------------------------------
    def add(self, obj):
        cls = type(obj)
        with self._lock:
            tab = self._load(cls)
            if obj.id in tab:
                raise ValueError(f"duplicate id {obj.id}")
            ws = self._worksheet(cls)
            self._with_retry(ws.append_row, to_row(obj), value_input_option="USER_ENTERED")
            tab[obj.id] = copy.deepcopy(obj)
            self._rowno[cls.__table__][obj.id] = len(tab) + 1
        return obj

    def get(self, cls, id):
        o = self._load(cls).get(id)
        return copy.deepcopy(o) if o is not None else None

    def all(self, cls):
        return [copy.deepcopy(o) for o in self._load(cls).values()]

    def find(self, cls, pred=None, **eq):
        return [copy.deepcopy(o) for o in self._load(cls).values()
                if all(getattr(o, k) == v for k, v in eq.items()) and (pred is None or pred(o))]

    def update(self, obj):
        cls = type(obj)
        with self._lock:
            tab = self._load(cls)
            if obj.id not in tab:
                raise KeyError(obj.id)
            row = self._rowno[cls.__table__][obj.id]
            ws = self._worksheet(cls)
            self._with_retry(ws.update, f"A{row}", [to_row(obj)], value_input_option="USER_ENTERED")
            tab[obj.id] = copy.deepcopy(obj)
        return obj

    def delete(self, cls, id):
        with self._lock:
            tab = self._load(cls)
            if id not in tab:
                return
            row = self._rowno[cls.__table__][id]
            self._with_retry(self._worksheet(cls).delete_rows, row)
            del tab[id]
            # re-number following rows
            for k, r in self._rowno[cls.__table__].items():
                if r > row:
                    self._rowno[cls.__table__][k] = r - 1
            self._rowno[cls.__table__].pop(id, None)

    def upsert(self, obj):
        if self.get(type(obj), obj.id) is None:
            return self.add(obj)
        return self.update(obj)
