from __future__ import annotations

from typing import Dict, List, Tuple

from packages.core.dtos import EvidenceCandidate
from packages.retrieval.base import IVectorRetriever


class HybridRetriever(IVectorRetriever):
    def __init__(self, *, vector_retriever: IVectorRetriever, fts_retriever: IVectorRetriever) -> None:
        self._vector = vector_retriever
        self._fts = fts_retriever

    @staticmethod
    def _normalize(candidates: List[EvidenceCandidate]) -> Dict[Tuple[str, str], float]:
        if not candidates:
            return {}
        max_score = max(float(candidate.score or 0.0) for candidate in candidates)
        if max_score <= 0:
            return {
                (str(candidate.section_id or ""), str(candidate.policy_version_id)): 0.0
                for candidate in candidates
            }
        return {
            (str(candidate.section_id or ""), str(candidate.policy_version_id)): float(candidate.score or 0.0) / max_score
            for candidate in candidates
        }

    def retrieve(self, *, tenant_id, query: str, scope=None, user=None, top_k: int = 10) -> List[EvidenceCandidate]:
        vector_results = self._vector.retrieve(tenant_id=tenant_id, query=query, scope=scope, user=user, top_k=top_k)
        fts_results = self._fts.retrieve(tenant_id=tenant_id, query=query, scope=scope, user=user, top_k=top_k)

        vector_norm = self._normalize(vector_results)
        fts_norm = self._normalize(fts_results)

        merged: Dict[Tuple[str, str], EvidenceCandidate] = {}

        for candidate in vector_results:
            key = (str(candidate.section_id or ""), str(candidate.policy_version_id))
            merged[key] = candidate.model_copy(deep=True)

        for candidate in fts_results:
            key = (str(candidate.section_id or ""), str(candidate.policy_version_id))
            if key not in merged:
                merged[key] = candidate.model_copy(deep=True)

        final: List[EvidenceCandidate] = []
        for key, candidate in merged.items():
            v_score = vector_norm.get(key, 0.0)
            f_score = fts_norm.get(key, 0.0)
            combined = max(v_score, f_score)

            if v_score >= f_score and v_score > 0:
                retriever_source = "pgvector"
            elif f_score > 0:
                retriever_source = "pgsql_fts"
            else:
                retriever_source = candidate.source

            metadata = dict(candidate.metadata or {})
            metadata["retriever"] = "hybrid"
            metadata["retriever_source"] = retriever_source

            final.append(
                candidate.model_copy(
                    update={
                        "score": combined,
                        "source": "hybrid",
                        "metadata": metadata,
                    }
                )
            )

        final.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        return final[: max(1, int(top_k))]
