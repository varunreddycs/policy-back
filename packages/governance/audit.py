from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID


@dataclass(frozen=True)
class AuditEvent:
	tenant_id: UUID
	event_type: str
	created_at: datetime
	correlation_id: Optional[str] = None
	payload: Dict[str, Any] = None  # type: ignore[assignment]


class AuditLog:
	"""Audit log writer/reader (Phase 2 scaffold)."""

	def write(self, event: AuditEvent) -> None:
		return
