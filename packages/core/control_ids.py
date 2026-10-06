"""NIST control-identifier parsing shared by retrieval, answering and DTO code.

Lives in core (no dependency on retrieval DTOs) so non-retrieval code can use
the canonical definition of a control ID without a layering inversion.
"""

from __future__ import annotations

import re

# NIST-style control identifiers: AC-2, ac-2, IA-5(1), SC-7(3).
# No trailing \b — ")" is not a word character, so a trailing boundary would
# refuse to match the enhancement suffix and silently truncate "IA-5(1)" to
# "IA-5".
_CONTROL_ID_RE = re.compile(r"\b([A-Za-z]{2})-(\d+)(\(\d+\))?")

_TITLE_SEPARATORS = " \t-–—:."


# SP 800-53 Rev 5 control families. The regex alone accepts any "XX-n", so a
# department code like "HR-4" in a non-NIST document would otherwise be
# presented as a NIST control.
NIST_800_53_FAMILIES = frozenset(
    {
        "AC", "AT", "AU", "CA", "CM", "CP", "IA", "IR", "MA", "MP",
        "PE", "PL", "PM", "PS", "PT", "RA", "SA", "SC", "SI", "SR",
    }
)

def _canonical(match: re.Match[str]) -> str:
    return f"{match.group(1).upper()}-{int(match.group(2))}{match.group(3) or ''}"


def extract_control_ids(text: str) -> set[str]:
    """Normalized control IDs named in ``text`` (e.g. {"AC-2", "IA-5(1)"}).

    Normalizes case and strips leading zeros so "ac-02" and "AC-2" are one id.
    """
    return {_canonical(m) for m in _CONTROL_ID_RE.finditer(text or "")}


def normalize_control_ids(text: str) -> str:
    """Rewrite control IDs in a query to canonical form before embedding.

    "what does ac-02 require" -> "what does AC-2 require", so the embedded text
    matches how identifiers appear in the corpus.
    """
    if not text:
        return text
    return _CONTROL_ID_RE.sub(_canonical, text)


def primary_control_id(text: str | None) -> str | None:
    """Canonical form of the first control ID in ``text`` by position, or None."""
    if not text:
        return None
    match = _CONTROL_ID_RE.search(text)
    return _canonical(match) if match else None


def strip_control_prefix(title: str | None, control_id: str | None) -> str | None:
    """Drop a leading control ID from ``title``, leaving the control's name.

    The sectioner emits "AC-2 Account Management" while the NIST seed emits a
    bare "Account Management"; both must yield the same control name. Returns
    None when nothing is left.
    """
    if title is None:
        return None
    result = title
    if control_id:
        match = _CONTROL_ID_RE.match(title.lstrip())
        if match and _canonical(match) == control_id.upper():
            result = title.lstrip()[match.end() :].lstrip(_TITLE_SEPARATORS)
    result = result.strip()
    return result or None


def is_nist_control_id(control_id: str | None) -> bool:
    """True when ``control_id`` belongs to a real SP 800-53 Rev 5 family."""
    return bool(control_id) and control_id[:2].upper() in NIST_800_53_FAMILIES
