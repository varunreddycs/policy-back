"""S3: attach officially mapped controls (NIST crosswalk) to citations.

Display metadata only. Nothing here reaches the LLM prompt, grounding, or verification, and mappings
are never chained (800-53 -> CSF -> ISO is not an authoritative mapping).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence

from packages.core.dtos import CitationItem, RelatedControl
from packages.db.repositories.base import IReferenceRepository
from packages.db.repositories.repo_dtos import PolicyReferenceDTO

logger = logging.getLogger(__name__)

MAX_RELATED_CONTROLS = 12

# (canonical framework, label prefix, accepted name/label prefixes). Anything outside this table is
# reported as unknown rather than guessed from free text.
_FRAMEWORKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("NIST CSF 2.0", "CSF 2.0", ("NIST CSF 2.0", "CSF 2.0")),
    (
        "NIST SP 800-53 Rev 5.2.0",
        "SP 800-53 Rev 5.2.0",
        ("NIST SP 800-53 Rev 5.2.0", "SP 800-53 Rev 5.2.0", "800-53"),
    ),
    ("ISO/IEC 27001:2022", "ISO/IEC 27001:2022", ("ISO/IEC 27001:2022",)),
)


def _match_framework(text: str | None) -> tuple[str, str, str] | None:
    """Return (framework, label prefix, remainder after the matched prefix) for a known prefix."""
    if not text:
        return None
    for framework, label_prefix, prefixes in _FRAMEWORKS:
        for prefix in sorted(prefixes, key=len, reverse=True):
            if text.startswith(prefix):
                return framework, label_prefix, text[len(prefix) :].strip()
    return None


def _natural_key(value: str) -> list[tuple[int, int, str]]:
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"(\d+)", value) if p]


def _other_side(ref: PolicyReferenceDTO, section_id: uuid.UUID) -> RelatedControl | None:
    mapping_source = ref.mapping_source or ""
    relationship = ref.relationship_type or "related"
    if ref.source_section_id == section_id and ref.target_section_id != section_id:
        path, other_id = ref.target_section_path, ref.target_section_id
        known = (
            _match_framework(ref.mapping_revision)
            or _match_framework(ref.target_policy_name)
            or _match_framework(ref.target_external_label)
        )
        label_rest = _match_framework(ref.target_external_label)
        control_id = path or (label_rest[2] if label_rest else ref.target_external_label)
        unknown_framework = ref.mapping_revision or "unknown"
    elif ref.target_section_id == section_id and ref.source_section_id != section_id:
        path, other_id = ref.source_section_path, ref.source_section_id
        known = _match_framework(ref.source_policy_name)
        control_id = path
        # mapping_revision names the target framework, so it says nothing about the source side.
        unknown_framework = "unknown"
    else:
        return None
    if not control_id:
        return None
    if known is None:
        framework = unknown_framework
        label = f"{framework} {control_id}"
    else:
        framework, label_prefix, _ = known
        label = f"{label_prefix} {control_id}"
    return RelatedControl(
        label=label,
        framework=framework,
        control_id=control_id,
        section_id=other_id,
        relationship=relationship,
        mapping_source=mapping_source,
    )


def derive_related_controls(
    refs: Sequence[PolicyReferenceDTO], section_id: uuid.UUID, *, limit: int = MAX_RELATED_CONTROLS
) -> tuple[list[RelatedControl], bool]:
    """Controls directly mapped to *section_id*, deduped, sorted, capped. Returns (controls, truncated)."""
    found: dict[tuple[str, str], RelatedControl] = {}
    for ref in refs:
        if ref.mapping_source is None:
            continue
        control = _other_side(ref, section_id)
        if control is not None:
            found.setdefault((control.framework, control.control_id), control)
    ordered = sorted(found.values(), key=lambda c: (c.framework, _natural_key(c.control_id)))
    return ordered[:limit], len(ordered) > limit


def enrich_citations(
    citations: Sequence[CitationItem],
    *,
    references_repo: IReferenceRepository,
    tenant_id: uuid.UUID,
) -> list[CitationItem]:
    """Attach related controls with ONE repository lookup for all cited sections."""
    section_ids = sorted({c.section_id for c in citations if c.section_id is not None}, key=str)
    if not section_ids:
        return list(citations)
    refs = references_repo.list_mappings_for_sections(tenant_id=tenant_id, section_ids=section_ids)
    enriched: list[CitationItem] = []
    for citation in citations:
        if citation.section_id is None:
            enriched.append(citation)
            continue
        controls, truncated = derive_related_controls(refs, citation.section_id)
        enriched.append(
            citation.model_copy(update={"related_controls": controls, "related_controls_truncated": truncated})
        )
    return enriched
