from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceCandidate(BaseModel):
	"""A single candidate chunk/section returned by retrieval."""

	policy_id: UUID
	policy_version_id: UUID
	section_id: Optional[UUID] = None
	text: str
	score: float = Field(default=0.0)
	metadata: Dict[str, Any] = Field(default_factory=dict)


class AskRequest(BaseModel):
	tenant_id: UUID
	question: str
	as_of: Optional[date] = None
	correlation_id: Optional[str] = None


class AnswerResponse(BaseModel):
	answer: str
	evidence: List[EvidenceCandidate] = Field(default_factory=list)
	created_at: datetime
