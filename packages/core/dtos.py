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
	source: str = Field(default="policy_sections")
	metadata: Dict[str, Any] = Field(default_factory=dict)


class UserContext(BaseModel):
	tenant_id: UUID
	email: Optional[str] = None
	role: Optional[str] = None
	department: Optional[str] = None


class PolicyScope(BaseModel):
	policy_ids: Optional[List[UUID]] = None
	policy_types: Optional[List[str]] = None
	only_current: bool = True


class AskRequest(BaseModel):
	tenant_id: UUID
	question: str
	mode: Optional[str] = Field(default=None, description="Optional mode (e.g., 'strict', 'draft')")
	scope: Optional[PolicyScope] = None
	user: Optional[UserContext] = None
	as_of: Optional[date] = None
	correlation_id: Optional[str] = None


class AnswerResponse(BaseModel):
	answer: str
	audit_id: Optional[UUID] = None
	citations: List[str] = Field(default_factory=list)
	confidence: Optional[float] = None
	refusal_reason: Optional[str] = None
	evidence: List[EvidenceCandidate] = Field(default_factory=list)
	created_at: datetime

