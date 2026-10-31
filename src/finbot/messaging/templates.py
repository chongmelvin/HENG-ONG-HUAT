"""Personality (PRD 4.6): Singlish-casual, light touches, scolds on overspend.

Every event has a neutral variant plus optional light and scold variants. The numbers and
buttons live in the caller; only the surrounding words come from here. Security, money errors and
sensitive content never call this module and stay in plain English.
"""
from __future__ import annotations

import random
from typing import Optional

from ..domain.enums import Persona
from ..domain.models import Settings

EVENTS: dict[str, dict[str, list[str]]] = {
    "saved": {"neutral": ["Saved:"], "light": ["Saved lah.", "Ok, saved.", "Saved ah."]},
    "warn80": {"neutral": ["{label} is at {pct}% of its limit."],
               "light": ["Eh, {label} at {pct}% already ah. Slow down a bit.", "{label} at {pct}% leh. Careful ah."]},
    "breach_first": {"neutral": ["{label} is over its limit by {over} ({spent} of {limit})."],
                     "light": ["{label} over by {over} leh ({spent} of {limit})."],
                     "scold": ["Aiyo, {label} over by {over} leh ({spent} of {limit}). Stop whack so much already lah.",
                               "Wah, {label} over by {over} ({spent} of {limit}). Cannot like this ah."]},
    "breach_still": {"neutral": ["{label}: still over by {over}."]},
    "breach_firm": {"neutral": ["{label} has been over its limit {n} months in a row."],
                    "light": ["{label} over again, {n} months in a row."],
                    "scold": ["{label} over again, {n} months in a row already. Really must control now."]},
    "under_budget": {"neutral": ["{label} finished {amt} under budget."],
                     "light": ["Wah, steady. {label} finished {amt} under budget."]},
    "reconciled": {"neutral": ["Reconciled."], "light": ["Wah, all tally. Steady."]},
    "missing_amount": {"neutral": ["I couldn't find an amount. How much was it?"],
                       "light": ["Sorry, cannot catch the amount. How much was it?"]},
    "bill": {"neutral": ["Reminder:"], "light": ["Reminder ah:"]},
    "chase": {"neutral": ["{name} has not repaid {amt} ({days} days)."],
              "light": ["{name} still never pay {amt} leh. {days} days already."]},
    "voucher": {"neutral": ["{scheme} voucher {amt} expires in {days} days."],
                "light": ["{scheme} voucher {amt} expiring in {days} days. Use it or lose it ah."]},
    "report_good": {"neutral": ["{month} report is here."], "light": ["{month} report is here. Savings rate {rate}%, steady leh."]},
    "report_mid": {"neutral": ["{month} report is here."], "light": ["{month} report is here. Savings rate {rate}%, so-so leh."]},
    "report_low": {"neutral": ["{month} report is here."], "light": ["{month} report is here. Savings rate only {rate}%, aiyo."]},
    "help_intro": {"neutral": ["Quick list:"], "light": ["Need help ah? Quick list:"]},
    "trip_on": {"neutral": ["Trip mode on."], "light": ["Trip mode on. Enjoy, but don't go crazy lah."]},
    "welcome_back": {"neutral": ["Welcome back."], "light": ["Welcome back lah."]},
}


class Messenger:
    def __init__(self, settings: Settings, seed: Optional[int] = None) -> None:
        self.settings = settings
        self._rng = random.Random(seed)
        self._last: dict[str, int] = {}

    def _variants(self, event: str, kind: str) -> list[str]:
        return EVENTS[event].get(kind) or EVENTS[event]["neutral"]

    def say(self, event: str, scold: bool = False, **kw) -> str:
        persona = self.settings.persona
        if persona == Persona.OFF:
            kind = "neutral"
        elif scold and persona == Persona.LIGHT and "scold" in EVENTS[event]:
            kind = "scold"
        elif persona == Persona.SCOLD_OFF:
            kind = "light" if event not in ("breach_first", "breach_firm") else "neutral"
        else:
            kind = "light"
        options = self._variants(event, kind)
        i = self._rng.randrange(len(options))
        if len(options) > 1 and self._last.get(event) == i:
            i = (i + 1) % len(options)          # never repeat the same line twice in a row
        self._last[event] = i
        return options[i].format(**kw)
