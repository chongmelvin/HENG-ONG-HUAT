from __future__ import annotations

from datetime import datetime

from ..domain.models import AuditEntry
from .ids import new_id


def audit(repo, now: datetime, action: str, table: str, record_id: str = "", detail: str = "") -> None:
    repo.add(AuditEntry(id=new_id("au"), at=now, action=action, table=table, record_id=record_id, detail=detail))
