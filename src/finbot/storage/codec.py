"""Row codec: dataclass <-> flat string cells (Google Sheets friendly).

Scalars become plain cells so the Sheet stays hand-editable. Lists, dicts and
nested dataclasses are JSON in a single cell. Decimals are strings.
"""
from __future__ import annotations

import dataclasses
import json
import types
import typing
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin


def _is_optional(tp) -> tuple[bool, Any]:
    if get_origin(tp) in (typing.Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1 and len(get_args(tp)) == 2:
            return True, args[0]
    return False, tp


def _jsonable(v: Any) -> Any:
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: _jsonable(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return v


def _from_json(tp, v: Any) -> Any:
    opt, inner = _is_optional(tp)
    if opt:
        return None if v is None else _from_json(inner, v)
    origin = get_origin(tp)
    if origin is list:
        (arg,) = get_args(tp)
        return [_from_json(arg, x) for x in (v or [])]
    if origin is dict:
        return dict(v or {})
    if dataclasses.is_dataclass(tp):
        hints = typing.get_type_hints(tp)
        return tp(**{f.name: _from_json(hints[f.name], v[f.name]) for f in dataclasses.fields(tp) if f.name in v})
    if tp is Decimal:
        return Decimal(str(v))
    if tp is datetime:
        return datetime.fromisoformat(v)
    if tp is date:
        return date.fromisoformat(v)
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(v)
    if tp is bool:
        return bool(v)
    if tp in (int, float, str):
        return tp(v)
    return v


def encode_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (list, dict)) or dataclasses.is_dataclass(v):
        return json.dumps(_jsonable(v), ensure_ascii=False)
    return str(v)


def decode_cell(tp, s: str) -> Any:
    opt, inner = _is_optional(tp)
    if s == "" or s is None:
        if opt:
            return None
        if inner is str:
            return ""
        if get_origin(inner) is list:
            return []
        if get_origin(inner) is dict:
            return {}
        if inner is Decimal:
            return Decimal("0.00")
        if inner is bool:
            return False
        if inner in (int, float):
            return inner(0)
        raise ValueError("empty cell for required field")
    tp = inner
    origin = get_origin(tp)
    if origin in (list, dict) or dataclasses.is_dataclass(tp):
        return _from_json(tp, json.loads(s))
    if tp is bool:
        return str(s).strip().upper() in ("TRUE", "1", "YES")
    return _from_json(tp, s)


def columns(cls) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


def to_row(obj) -> list[str]:
    return [encode_cell(getattr(obj, f.name)) for f in dataclasses.fields(obj)]


def from_row(cls, row: list[str]):
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for i, f in enumerate(dataclasses.fields(cls)):
        cell = row[i] if i < len(row) else ""
        kwargs[f.name] = decode_cell(hints[f.name], cell)
    return cls(**kwargs)
