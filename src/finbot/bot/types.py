from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Button:
    label: str
    data: str


@dataclass
class Reply:
    """Transport-neutral reply. The Telegram adapter turns this into messages, keyboards and files."""
    text: str
    buttons: list[list[Button]] = field(default_factory=list)
    files: list[tuple[str, bytes]] = field(default_factory=list)       # (filename, content)
    file_ids: list[str] = field(default_factory=list)                  # existing Telegram files to re-send
    delete_user_message: bool = False                                   # used for PIN messages
    auto_delete_s: Optional[int] = None                                 # sensitive replies (optional)
    sensitive: bool = False


def rows(*row: list[tuple[str, str]]) -> list[list[Button]]:
    return [[Button(l, d) for l, d in r] for r in row]
