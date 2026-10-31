"""Holdings, automatic prices, analysis (PRD 6.2). Stocks, ETFs and crypto are priced automatically.

Price sources are pluggable (open question in the PRD: which market-data source). Defaults here:
Yahoo Finance's public chart endpoint for stocks/ETFs and CoinGecko for crypto. If a feed fails the
last known price is kept and the holding is reported as stale with its date.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Protocol

import httpx

from ..core.audit import audit
from ..core.ids import new_id
from ..core.ledger import LedgerError
from ..domain.enums import ACTIVE, HoldingType
from ..domain.models import Holding, PricePoint
from ..domain.money import ZERO
from .fx import FxProvider

log = logging.getLogger(__name__)
CONCENTRATION_LIMIT = Decimal("0.30")


class PriceError(RuntimeError):
    pass


class PriceProvider(Protocol):
    def price(self, h: Holding, on: date) -> tuple[Decimal, str]:
        """Return (price per unit, currency)."""


class YahooProvider:
    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._c = client or httpx.Client(timeout=10, headers={"User-Agent": "finbot/0.2"})

    def price(self, h: Holding, on: date) -> tuple[Decimal, str]:
        try:
            r = self._c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{h.symbol}", params={"range": "5d", "interval": "1d"})
            r.raise_for_status()
            meta = r.json()["chart"]["result"][0]["meta"]
            return Decimal(str(meta["regularMarketPrice"])), meta.get("currency", "USD")
        except Exception as e:
            raise PriceError(f"yahoo {h.symbol}") from e


class CoinGeckoProvider:
    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._c = client or httpx.Client(timeout=10)

    def price(self, h: Holding, on: date) -> tuple[Decimal, str]:
        try:
            r = self._c.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": h.symbol.lower(), "vs_currencies": "sgd"})
            r.raise_for_status()
            return Decimal(str(r.json()[h.symbol.lower()]["sgd"])), "SGD"
        except Exception as e:
            raise PriceError(f"coingecko {h.symbol}") from e


class RoutingProvider:
    def __init__(self, stocks: PriceProvider, crypto: PriceProvider) -> None:
        self.stocks, self.crypto = stocks, crypto

    def price(self, h: Holding, on: date):
        return (self.crypto if h.type == HoldingType.CRYPTO else self.stocks).price(h, on)


class StaticPrices:
    def __init__(self, prices: dict[str, Decimal], fail: tuple[str, ...] = ()) -> None:
        self.prices, self.fail = prices, fail

    def price(self, h: Holding, on: date):
        if h.symbol in self.fail:
            raise PriceError(h.symbol)
        return self.prices[h.symbol], "SGD"


def add_holding(repo, now: datetime, *, name: str, symbol: str, type: HoldingType, units: Decimal, cost_basis: Decimal,
                platform: str = "") -> Holding:
    if units <= 0 or cost_basis <= 0:
        raise LedgerError("Units and cost basis must be positive.")
    h = repo.add(Holding(id=new_id("ho"), name=name, symbol=symbol, type=type, units=units, cost_basis=cost_basis, platform=platform))
    audit(repo, now, "create", "holdings", h.id, name)
    return h


@dataclass
class RefreshResult:
    updated: list[Holding]
    stale: list[Holding]


def refresh_prices(repo, provider: PriceProvider, today: date, fx: Optional[FxProvider] = None) -> RefreshResult:
    ok, stale = [], []
    for h in repo.find(Holding, status=ACTIVE):
        try:
            price, cur = provider.price(h, today)
            if cur != "SGD":
                if fx is None:
                    raise PriceError("no fx for " + cur)
                price = price * fx.rate(cur, "SGD", today)
            h.price, h.price_date = price.quantize(Decimal("0.0001")), today
            repo.update(h)
            repo.add(PricePoint(id=new_id("pp"), holding_id=h.id, date=today, price=h.price))
            ok.append(h)
        except Exception as e:
            log.warning("price refresh failed for %s: %s", h.symbol, e)
            stale.append(h)             # keep the last known price and its date
    return RefreshResult(ok, stale)


@dataclass
class HoldingRow:
    holding: Holding
    value: Decimal
    gain: Decimal
    return_pct: float
    share_pct: float
    month_move: Decimal
    stale: bool


def table(repo, today: date, month_start: Optional[date] = None) -> list[HoldingRow]:
    hs = repo.find(Holding, status=ACTIVE)
    total = sum((h.value for h in hs), ZERO)
    rows = []
    for h in hs:
        move = ZERO
        if month_start:
            pts = sorted([p for p in repo.find(PricePoint, holding_id=h.id) if p.date <= month_start], key=lambda p: p.date)
            if pts:
                move = ((h.price - pts[-1].price) * h.units).quantize(Decimal("0.01"))
        gain = h.value - h.cost_basis
        rows.append(HoldingRow(h, h.value, gain, float(gain / h.cost_basis * 100), float(h.value / total * 100) if total else 0.0,
                               move, bool(h.price_date and (today - h.price_date).days > 3)))
    return sorted(rows, key=lambda r: -r.value)


def concentration_flags(repo, limit: Decimal = CONCENTRATION_LIMIT) -> list[HoldingRow]:
    return [r for r in table(repo, date.today()) if r.share_pct / 100 > float(limit)]


def by_type(repo) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for h in repo.find(Holding, status=ACTIVE):
        k = "Crypto" if h.type == HoldingType.CRYPTO else "Stocks and ETFs"
        out[k] = out.get(k, ZERO) + h.value
    return out
