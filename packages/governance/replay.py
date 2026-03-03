from __future__ import annotations

from typing import Iterable

from packages.governance.audit import AuditEvent


def replay(events: Iterable[AuditEvent]) -> None:
	"""Replay audit events (Phase 2 scaffold)."""
	for _ in events:
		pass
