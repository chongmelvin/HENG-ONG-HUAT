from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTHS.update({"sept": 9})


class DateError(ValueError):
    pass


def parse_day_month(day: int, mon: int, year: Optional[int], today: date) -> date:
    y = year or today.year
    try:
        return date(y, mon, day)
    except ValueError as e:
        raise DateError(f"{day} {mon} is not a real date") from e


def relative(token: str, today: date) -> Optional[date]:
    t = token.lower()
    if t in ("y", "yday", "yesterday"):
        return today - timedelta(days=1)
    if t == "today":
        return today
    m = re.fullmatch(r"-(\d{1,3})d", t)
    if m:
        return today - timedelta(days=int(m.group(1)))
    return None


def future_fix(d: date, today: date) -> Optional[date]:
    """25 Dec typed in October is in the future. Offer last year's date if that is valid."""
    if d <= today:
        return None
    try:
        return date(d.year - 1, d.month, d.day)
    except ValueError:
        return None
