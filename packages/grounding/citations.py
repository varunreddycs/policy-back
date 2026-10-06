"""Evidence-handle citation parsing and verification (S1).

Unifies the two conflicting citation formats. The system prompt asked for
control-ids ("AC-2") while the user prompt demanded
"[policy_version_id=... section_id=...]", so the model was given contradictory
instructions and the returned citations were built from retrieval ranking
instead of from what the model actually cited.

Evidence is now labelled [E1]..[En] in the prompt and the model cites by
handle. A handle is short enough to be reliably reproduced, unambiguous, and
maps back to exactly one retrieved section — so a citation can be *verified*
rather than assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from packages.core.dtos import EvidenceCandidate

# [E1], [E2, E3], [E1][E4] — tolerant of the shapes models actually emit.
_HANDLE_BLOCK_RE = re.compile(r"\[\s*(E\d+(?:\s*,\s*E\d+)*)\s*\]", re.IGNORECASE)
_HANDLE_RE = re.compile(r"E(\d+)", re.IGNORECASE)

# Legacy format, still accepted so an older prompt/model does not hard-fail.
_LEGACY_RE = re.compile(r"\[policy_version_id=([^\s\]]+)\s+section_id=([^\s\]]+)\]")


def handle_for(index: int) -> str:
    """1-based evidence handle, e.g. 1 -> "E1"."""
    return f"E{index}"


@dataclass(frozen=True, slots=True)
class CitedSpan:
    """A claim in the answer and the evidence handle(s) it cites."""

    text: str
    handles: tuple[str, ...]


@dataclass(slots=True)
class CitationCheck:
    """Outcome of verifying one answer against the evidence it was given."""

    cited_handles: list[str] = field(default_factory=list)
    valid_handles: list[str] = field(default_factory=list)
    unknown_handles: list[str] = field(default_factory=list)
    uncited_sentences: list[str] = field(default_factory=list)
    total_sentences: int = 0

    @property
    def has_citations(self) -> bool:
        return bool(self.valid_handles)

    @property
    def hallucinated_handles(self) -> bool:
        """The model cited evidence that was never supplied."""
        return bool(self.unknown_handles)

    @property
    def citation_density(self) -> float:
        """Share of substantive sentences carrying at least one citation."""
        if self.total_sentences <= 0:
            return 0.0
        cited = self.total_sentences - len(self.uncited_sentences)
        return max(0.0, min(1.0, cited / self.total_sentences))


def extract_handles(text: str) -> list[str]:
    """Every evidence handle cited in ``text``, in order, de-duplicated."""
    seen: dict[str, None] = {}
    for block in _HANDLE_BLOCK_RE.finditer(text or ""):
        for match in _HANDLE_RE.finditer(block.group(1)):
            seen.setdefault(f"E{int(match.group(1))}", None)
    return list(seen)


def extract_legacy_references(text: str) -> list[tuple[str, str]]:
    """(policy_version_id, section_id) pairs in the pre-S1 citation format."""
    return [(m.group(1), m.group(2)) for m in _LEGACY_RE.finditer(text or "")]


def strip_citations(text: str) -> str:
    """Remove citation markers so the prose can be compared to source text."""
    cleaned = _HANDLE_BLOCK_RE.sub(" ", text or "")
    cleaned = _LEGACY_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def split_sentences(text: str) -> list[str]:
    """Rough sentence split; good enough to measure citation density."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if p.strip()]


# A sentence that makes no claim needs no citation — flagging these as
# ungrounded would refuse perfectly good answers over their framing.
_NON_CLAIM_PREFIXES = (
    "based on",
    "according to",
    "here",
    "in summary",
    "summary",
    "the following",
    "these controls",
    "this answer",
)


def _is_claim(sentence: str) -> bool:
    stripped = sentence.strip().lstrip("-*•0123456789. ").lower()
    if len(stripped) < 25:
        return False
    return not stripped.startswith(_NON_CLAIM_PREFIXES)


def check_citations(answer: str, candidates: list[EvidenceCandidate]) -> CitationCheck:
    """Verify which supplied evidence the answer actually cites."""
    known = {handle_for(i) for i in range(1, len(candidates) + 1)}
    cited = extract_handles(answer)

    check = CitationCheck(
        cited_handles=cited,
        valid_handles=[h for h in cited if h in known],
        unknown_handles=[h for h in cited if h not in known],
    )

    claims = [s for s in split_sentences(answer) if _is_claim(s)]
    check.total_sentences = len(claims)
    check.uncited_sentences = [s for s in claims if not extract_handles(s)]
    return check


def normalize_for_match(text: str) -> str:
    """Lowercase, collapse whitespace, drop punctuation that varies in quoting."""
    lowered = (text or "").lower()
    lowered = re.sub(r"[\u2018\u2019\u201c\u201d]", "'", lowered)
    lowered = re.sub(r"[^a-z0-9'\s-]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def is_supported_substring(
    snippet: str, source: str, *, threshold: float = 0.95
) -> bool:
    """True when ``snippet`` appears in ``source`` verbatim or near-verbatim.

    Exact containment first (cheap); otherwise slide a window of the snippet's
    length over the source and take the best fuzzy ratio, so a quote that
    differs only in whitespace or a stray character still verifies.
    """
    norm_snippet = normalize_for_match(snippet)
    norm_source = normalize_for_match(source)
    if not norm_snippet or not norm_source:
        return False
    if norm_snippet in norm_source:
        return True
    if len(norm_snippet) > len(norm_source):
        return False

    matcher = SequenceMatcher(None, norm_snippet, norm_source, autojunk=False)
    return matcher.quick_ratio() >= threshold and matcher.ratio() >= threshold
