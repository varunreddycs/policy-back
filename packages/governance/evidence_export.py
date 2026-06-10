from __future__ import annotations

from typing import Any, Dict, List

from packages.core.dtos import EvidenceCandidate


def export_evidence_packet(evidence: List[EvidenceCandidate]) -> Dict[str, Any]:
    return {"evidence": [e.model_dump(mode="json") for e in evidence]}
