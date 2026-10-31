"""Money helpers. All amounts are Decimal with 2 decimal places (SGD)."""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def D(value) -> Decimal:
    """Parse anything numeric into a 2dp Decimal. Raises ValueError on junk."""
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    try:
        s = str(value).strip().replace(",", "").replace("S$", "").replace("$", "")
        return Decimal(s).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"not a number: {value!r}") from e


def fmt(amount: Decimal, dec: int = 2, sign: bool = False) -> str:
    q = Decimal(1).scaleb(-dec)
    a = abs(amount).quantize(q, rounding=ROUND_HALF_UP)
    s = f"S${a:,.{dec}f}"
    if amount < 0:
        return "-" + s
    return ("+" + s) if sign and amount > 0 else s


def split_equal(total: Decimal, n: int) -> tuple[Decimal, list[Decimal]]:
    """Split `total` into n shares. Returns (payer_share, [other shares]).

    Others get the rounded-down share; leftover cents go to the payer,
    so 80/3 -> payer 26.68, others 26.66 each.
    """
    if n < 1:
        raise ValueError("need at least one person")
    base = (total / n).quantize(CENT, rounding=ROUND_DOWN)
    others = [base] * (n - 1)
    payer = total - base * (n - 1)
    return payer, others


def split_percent(total: Decimal, percents: list[Decimal]) -> list[Decimal]:
    return [(total * p / 100).quantize(CENT, rounding=ROUND_DOWN) for p in percents]
