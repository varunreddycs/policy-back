from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class ConflictSignal:
	policy_id: UUID
	reason: str
	policy_version_id_a: Optional[UUID] = None
	policy_version_id_b: Optional[UUID] = None
