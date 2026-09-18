from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceCandidate(BaseModel):
    """A single candidate chunk/section returned by retrieval."""

    policy_id: UUID
    policy_version_id: UUID
    section_id: UUID | None = None
    text: str
    score: float = Field(default=0.0)
    source: str = Field(default="policy_sections")
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserContext(BaseModel):
    tenant_id: UUID
    email: str | None = None
    role: str | None = None
    department: str | None = None


class PolicyScope(BaseModel):
    policy_ids: list[UUID] | None = None
    policy_types: list[str] | None = None
    only_current: bool = True


class AskRequest(BaseModel):
    tenant_id: UUID
    question: str
    mode: str | None = Field(
        default=None, description="Optional mode (e.g., 'strict', 'draft')"
    )
    scope: PolicyScope | None = None
    user: UserContext | None = None
    as_of: date | None = None
    correlation_id: str | None = None


class CitationItem(BaseModel):
    policy_id: UUID
    policy_version_id: UUID
    section_id: UUID | None = None
    policy_name: str | None = None
    section_title: str | None = None
    section_path: str | None = None
    snippet: str
    score: float = Field(default=0.0)
    public_url: str | None = None


class RefusalCode(StrEnum):
    """Typed reason the engine declined to answer.

    For a compliance product the reason it did NOT answer is itself a finding an
    officer must act on, so each gate emits a distinct, queryable code.
    """

    NO_AUTHORITATIVE_CONTROL = "no_authoritative_control"
    DEPARTMENT_SCOPE_AMBIGUOUS = "department_scope_ambiguous"
    CONFLICTING_VERSIONS = "conflicting_versions"
    BELOW_GROUNDEDNESS_THRESHOLD = "below_groundedness_threshold"


class RefusalInfo(BaseModel):
    """Auditable refusal detail: typed code plus the signals that produced it."""

    code: RefusalCode
    explanation: str
    selected_bucket: str | None = None
    user_department: str | None = None
    candidates_considered: int = 0
    best_score: float | None = None
    threshold: float | None = None


class DecisionInfo(BaseModel):
    selected_bucket: str
    reason: str
    user_department: str | None = None
    primary_candidates: int = 0
    secondary_candidates: int = 0


class SecondaryEvidenceItem(BaseModel):
    policy_version_id: UUID
    section_id: UUID | None = None
    policy_name: str | None = None
    section_title: str | None = None
    score: float = Field(default=0.0)
    department_scope: str | None = None
    public_url: str | None = None


class AnswerResponse(BaseModel):
    answer: str
    audit_id: UUID | None = None
    citations: list[str] = Field(default_factory=list)
    citation_items: list[CitationItem] = Field(default_factory=list)
    decision: DecisionInfo | None = None
    retrieval_log: dict[str, Any] | None = None
    secondary_evidence: list[SecondaryEvidenceItem] = Field(default_factory=list)
    confidence: float | None = None
    refusal_reason: str | None = Field(
        default=None,
        description="Typed RefusalCode value; kept as a plain string for backward compatibility.",
    )
    refusal: RefusalInfo | None = None
    evidence: list[EvidenceCandidate] = Field(default_factory=list)
    created_at: datetime
