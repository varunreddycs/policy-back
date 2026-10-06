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
    as_of: date | None = Field(
        default=None,
        description=(
            "S2: answer from the policy versions authoritative on this date. "
            "Overrides only_current; a version is authoritative when it is the "
            "latest READY version of its policy effective on or before the date."
        ),
    )


class AskRequest(BaseModel):
    tenant_id: UUID
    # Q6: unbounded question text flowed straight into embeddings + the LLM as
    # cost amplification. 4000 chars is far above any real compliance question.
    question: str = Field(min_length=1, max_length=4000)
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
    control_id: str | None = Field(
        default=None,
        description="S3: canonical NIST control id this citation covers, e.g. 'AC-2(3)'.",
    )
    control_name: str | None = Field(
        default=None,
        description="S3: the control's name, e.g. 'Account Management'.",
    )
    snippet: str
    score: float = Field(default=0.0)
    public_url: str | None = None
    effective_date: date | None = Field(
        default=None,
        description="S2: when the cited version took effect — the auditor's anchor.",
    )
    version_label: str | None = None


class RefusalCode(StrEnum):
    """Typed reason the engine declined to answer.

    For a compliance product the reason it did NOT answer is itself a finding an
    officer must act on, so each gate emits a distinct, queryable code.
    """

    NO_AUTHORITATIVE_CONTROL = "no_authoritative_control"
    DEPARTMENT_SCOPE_AMBIGUOUS = "department_scope_ambiguous"
    CONFLICTING_VERSIONS = "conflicting_versions"
    BELOW_GROUNDEDNESS_THRESHOLD = "below_groundedness_threshold"
    UNGROUNDED_ANSWER = "ungrounded_answer"


class AnswerSource(StrEnum):
    """Where the returned answer text actually came from.

    Q2: an excerpt fallback is a materially weaker product than a generated
    answer, so the degradation must be visible on the response rather than silent.
    """

    LLM = "llm"
    EXCERPT_FALLBACK = "excerpt_fallback"
    REFUSAL = "refusal"


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
    as_of: date | None = Field(
        default=None,
        description="S2: the point-in-time this answer was evaluated against, when requested.",
    )
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


class GroundingInfo(BaseModel):
    """S1: post-generation verification of the answer against its citations.

    ``verified`` is the gate result; the rest is the evidence for it, so an
    officer (or an auditor) can see why an answer was allowed or refused.
    """

    verified: bool
    enforced: bool = Field(
        default=True,
        description="False when checks ran in report-only mode and could not refuse.",
    )
    faithfulness_score: float | None = None
    faithfulness_backend: str | None = None
    threshold: float | None = None
    cited_handles: list[str] = Field(default_factory=list)
    unknown_handles: list[str] = Field(
        default_factory=list,
        description="Handles the model cited that were never supplied to it.",
    )
    verified_citations: int = 0
    unverified_citations: int = 0
    citation_density: float | None = Field(
        default=None,
        description="Share of substantive claims carrying at least one citation.",
    )
    supported_claims: int = 0
    total_claims: int = 0
    unsupported_claims: list[str] = Field(default_factory=list)
    failure_reason: str | None = None


class AnswerResponse(BaseModel):
    answer: str
    audit_id: UUID | None = None
    citations: list[str] = Field(default_factory=list)
    citation_items: list[CitationItem] = Field(default_factory=list)
    decision: DecisionInfo | None = None
    retrieval_log: dict[str, Any] | None = None
    secondary_evidence: list[SecondaryEvidenceItem] = Field(default_factory=list)
    confidence: float | None = Field(
        default=None,
        description=(
            "Relevance heuristic (the fused retrieval score of the top evidence), "
            "NOT a calibrated probability that the answer is correct."
        ),
    )
    grounding_score: float | None = Field(
        default=None,
        description=(
            "Absolute similarity the refusal gate was evaluated against. "
            "Comparable across retrieval backends, unlike confidence."
        ),
    )
    refusal_reason: str | None = Field(
        default=None,
        description="Typed RefusalCode value; kept as a plain string for backward compatibility.",
    )
    refusal: RefusalInfo | None = None
    answer_source: AnswerSource = AnswerSource.LLM
    is_fallback: bool = Field(
        default=False,
        description="True when the answer text is a raw excerpt because the LLM was unavailable or failed.",
    )
    llm_error: str | None = Field(
        default=None,
        description="Why generation degraded to the fallback, when it did.",
    )
    grounding: GroundingInfo | None = None
    evidence: list[EvidenceCandidate] = Field(default_factory=list)
    created_at: datetime
