"""Traffic lights (PRD 4.3). All thresholds in one place; nothing else hard-codes them."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..domain.models import Settings

GREEN, YELLOW, RED = "🟢", "🟡", "🔴"
OK, WARN = "✅", "⚠️"


def budget_light(used_pct: float) -> str:
    if used_pct >= 100:
        return RED
    return YELLOW if used_pct >= 80 else GREEN


def pace_light(spent_frac: float, elapsed_frac: float) -> str:
    ahead = spent_frac - elapsed_frac
    if ahead <= 0:
        return GREEN
    return YELLOW if ahead <= 0.10 else RED


def savings_light(rate_pct: float, green: int = 30, yellow: int = 15) -> str:
    if rate_pct >= green:
        return GREEN
    return YELLOW if rate_pct >= yellow else RED


def bill_light(days_to_due: int, paid: bool = False) -> str:
    if paid:
        return GREEN
    if days_to_due <= 0:
        return RED
    return YELLOW if days_to_due <= 3 else GREEN


def owed_light(days_outstanding: int) -> str:
    if days_outstanding > 14:
        return RED
    return YELLOW if days_outstanding >= 7 else GREEN


def expiry_light(days_left: int) -> str:
    if days_left <= 30:
        return RED
    return YELLOW if days_left <= 60 else GREEN


def networth_light(change: Decimal, base: Decimal) -> str:
    if base == 0:
        return GREEN if change > 0 else ""
    pct = float(change / base * 100)
    if abs(pct) <= 0.2:
        return YELLOW
    return GREEN if pct > 0 else RED


def reconcile_icon(gap: Decimal) -> str:
    return OK if gap == 0 else RED


@dataclass
class Badge:
    """Wraps lights so the `indicators` setting can switch them off globally."""
    enabled: bool = True

    @classmethod
    def of(cls, settings: Settings) -> "Badge":
        return cls(settings.indicators)

    def __call__(self, light: str) -> str:
        return light if self.enabled else ""

    def pre(self, light: str) -> str:
        return f"{light} " if (self.enabled and light) else ""
