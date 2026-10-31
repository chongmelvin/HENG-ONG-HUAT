"""PIN gate for sensitive actions (PRD 9.4)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from ..domain.models import Settings

UNLOCK = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)
MAX_TRIES = 3
SENSITIVE = {"networth", "snapshot", "insurance", "coverage", "invest", "export", "balances", "edit_old", "delete_old"}


class PinError(ValueError):
    pass


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120_000).hex()


def validate_new_pin(pin: str) -> None:
    if not pin.isdigit():
        raise PinError("A PIN is digits only.")
    if len(pin) < 6:
        raise PinError("A PIN needs at least 6 digits.")
    if len(set(pin)) == 1:
        raise PinError("A PIN can't be all one digit. Choose a different one.")
    if pin in ("123456", "1234567", "12345678", "654321", "123123"):
        raise PinError("That PIN is too easy. Choose a different one of 6 or more digits.")


def set_pin(settings: Settings, pin: str) -> Settings:
    validate_new_pin(pin)
    settings.pin_salt = secrets.token_hex(8)
    settings.pin_hash = hash_pin(pin, settings.pin_salt)
    return settings


class PinGate:
    """Tracks unlock windows and lockouts in memory (they reset on restart, which fails safe)."""

    def __init__(self) -> None:
        self.unlocked_until: datetime | None = None
        self.locked_until: datetime | None = None
        self.fails = 0

    def is_unlocked(self, now: datetime) -> bool:
        return bool(self.unlocked_until and now < self.unlocked_until)

    def is_locked(self, now: datetime) -> bool:
        return bool(self.locked_until and now < self.locked_until)

    def try_pin(self, settings: Settings, pin: str, now: datetime) -> tuple[bool, str]:
        if self.is_locked(now):
            return False, "locked"
        if settings.pin_hash and hmac.compare_digest(hash_pin(pin, settings.pin_salt), settings.pin_hash):
            self.fails, self.unlocked_until = 0, now + UNLOCK
            return True, "ok"
        self.fails += 1
        if self.fails >= MAX_TRIES:
            self.fails, self.locked_until = 0, now + LOCKOUT
            return False, "locked"
        return False, f"{MAX_TRIES - self.fails}"
