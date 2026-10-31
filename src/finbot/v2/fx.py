"""Foreign exchange (PRD 6.1).

Preferred: you key the foreign price AND the SGD you actually paid, so the rate comes from your
own numbers. Fallbacks: a per-trip manual rate, then a fetched daily rate.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Optional, Protocol

import httpx

log = logging.getLogger(__name__)


class FxError(RuntimeError):
    pass


class FxProvider(Protocol):
    def rate(self, base: str, quote: str, on: date) -> Decimal: ...


class FrankfurterProvider:
    """ECB reference rates via frankfurter.app (free, no key). Cached per day."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._c = client or httpx.Client(timeout=10)
        self._cache: dict[tuple[str, str, date], Decimal] = {}

    def rate(self, base: str, quote: str, on: date) -> Decimal:
        key = (base, quote, on)
        if key in self._cache:
            return self._cache[key]
        try:
            r = self._c.get(f"https://api.frankfurter.app/{on.isoformat()}", params={"from": base, "to": quote})
            r.raise_for_status()
            v = Decimal(str(r.json()["rates"][quote]))
        except Exception as e:  # network, quota, schema
            raise FxError(f"could not fetch {base}/{quote}") from e
        self._cache[key] = v
        return v


class StaticFx:
    """Fixed rates for tests and offline use."""

    def __init__(self, rates: dict[tuple[str, str], Decimal]) -> None:
        self._r = rates

    def rate(self, base: str, quote: str, on: date) -> Decimal:
        try:
            return self._r[(base, quote)]
        except KeyError as e:
            raise FxError(f"no rate {base}/{quote}") from e


def derive_rate(foreign: Decimal, home: Decimal) -> Decimal:
    if foreign <= 0 or home <= 0:
        raise FxError("amounts must be positive")
    return (home / foreign).quantize(Decimal("0.00000001"))


def to_home(foreign: Decimal, *, currency: str, home_amount: Optional[Decimal], on: date,
            manual_rate: Optional[Decimal], provider: Optional[FxProvider]) -> tuple[Decimal, Decimal, str]:
    """Return (sgd_amount, rate, source). Source is 'entered', 'manual' or 'fetched'."""
    if home_amount is not None:
        return home_amount, derive_rate(foreign, home_amount), "entered"
    if manual_rate:
        return (foreign * manual_rate).quantize(Decimal("0.01")), manual_rate, "manual"
    if provider is None:
        raise FxError("no rate available; enter the SGD amount too")
    rate = provider.rate(currency, "SGD", on)
    return (foreign * rate).quantize(Decimal("0.01")), rate, "fetched"
