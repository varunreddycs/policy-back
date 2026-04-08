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


class CitationItem(BaseModel):
	policy_id: UUID
	policy_version_id: UUID
	section_id: Optional[UUID] = None
	policy_name: Optional[str] = None
	section_title: Optional[str] = None
	section_path: Optional[str] = None
	snippet: str
	score: float = Field(default=0.0)
	public_url: Optional[str] = None


class DecisionInfo(BaseModel):
	selected_bucket: str
	reason: str
	user_department: Optional[str] = None
	primary_candidates: int = 0
	secondary_candidates: int = 0


class SecondaryEvidenceItem(BaseModel):
	policy_version_id: UUID
	section_id: Optional[UUID] = None
	policy_name: Optional[str] = None
	section_title: Optional[str] = None
	score: float = Field(default=0.0)
	department_scope: Optional[str] = None
	public_url: Optional[str] = None


class AnswerResponse(BaseModel):
	answer: str
	audit_id: Optional[UUID] = None
	citations: List[str] = Field(default_factory=list)
	citation_items: List[CitationItem] = Field(default_factory=list)
	decision: Optional[DecisionInfo] = None
	retrieval_log: Optional[Dict[str, Any]] = None
	secondary_evidence: List[SecondaryEvidenceItem] = Field(default_factory=list)
	confidence: Optional[float] = None
	refusal_reason: Optional[str] = None
	evidence: List[EvidenceCandidate] = Field(default_factory=list)
	created_at: datetime

