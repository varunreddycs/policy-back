"""Shared NIST control-identifier handling (Q7).

Exact-identifier queries ("AC-2", "IA-5(1)") are how compliance users actually
search, and they were materially weaker on the Postgres path than on Cosmos:
the lexical boost lived only in the Cosmos provider, and the FTS OR-fallback
dropped tokens shorter than 3 characters, discarding the very control codes
being searched for.

This module is the single definition of what a control ID is, so the boost and
the normalization behave identically on every backend.

HyDE is deliberately NOT used anywhere here: generating a hypothetical document
degrades exact-identifier precision, which is the case this module exists for.
"""

from __future__ import annotations

import re

from packages.core.dtos import EvidenceCandidate

# NIST-style control identifiers: AC-2, ac-2, IA-5(1), SC-7(3).
# No trailing \b — ")" is not a word character, so a trailing boundary would
# refuse to match the enhancement suffix and silently truncate "IA-5(1)" to
# "IA-5".
_CONTROL_ID_RE = re.compile(r"\b([A-Za-z]{2})-(\d+)(\(\d+\))?")

# How much to boost a candidate whose section_path exactly matches a control
# named in the query — large enough to surface the named control to the top.
EXACT_ID_BOOST = 0.4


def extract_control_ids(text: str) -> set[str]:
    """Normalized control IDs named in ``text`` (e.g. {"AC-2", "IA-5(1)"}).

    Normalizes case and strips leading zeros so "ac-02" and "AC-2" are one id.
    """
    return {
        f"{m.group(1).upper()}-{int(m.group(2))}{m.group(3) or ''}"
        for m in _CONTROL_ID_RE.finditer(text or "")
    }


def normalize_control_ids(text: str) -> str:
    """Rewrite control IDs in a query to canonical form before embedding.

    "what does ac-02 require" -> "what does AC-2 require", so the embedded text
    matches how identifiers appear in the corpus.
    """
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        return f"{match.group(1).upper()}-{int(match.group(2))}{match.group(3) or ''}"

    return _CONTROL_ID_RE.sub(_replace, text)


def _candidate_ids(candidate: EvidenceCandidate) -> set[str]:
    """Control IDs identifying a candidate, from its path or title."""
    md = candidate.metadata or {}
    found: set[str] = set()
    for key in ("section_path", "title", "control_id"):
        value = md.get(key)
        if value:
            found |= extract_control_ids(str(value))
    return found


def boost_exact_control_matches(
    query: str,
    candidates: list[EvidenceCandidate],
    *,
    boost: float = EXACT_ID_BOOST,
    ceiling: float = 0.99,
) -> list[EvidenceCandidate]:
    """Surface candidates that ARE a control the query named.

    Returns a re-sorted list. When the query names no control, the input order
    is preserved untouched, so this is a no-op for ordinary questions.
    """
    named = extract_control_ids(query)
    if not named or not candidates:
        return candidates

    boosted: list[EvidenceCandidate] = []
    exact: list[bool] = []
    changed = False
    for candidate in candidates:
        if _candidate_ids(candidate) & named:
            md = dict(candidate.metadata or {})
            md["control_id_boost"] = boost
            md["pre_boost_score"] = float(candidate.score or 0.0)
            boosted.append(
                candidate.model_copy(
                    update={
                        "score": min(ceiling, float(candidate.score or 0.0) + boost),
                        "metadata": md,
                    }
                )
            )
            exact.append(True)
            changed = True
        else:
            boosted.append(candidate)
            exact.append(False)

    if not changed:
        return candidates

    # A section that IS the control the user named outranks one that merely
    # scores well, so sort on exactness first. Deciding this by arithmetic
    # alone would let a near neighbour tie the boosted score and win on sort
    # order — the exact failure this boost exists to prevent.
    order = sorted(
        range(len(boosted)),
        key=lambda i: (exact[i], float(boosted[i].score or 0.0)),
        reverse=True,
    )
    return [boosted[i] for i in order]
