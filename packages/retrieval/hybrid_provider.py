from __future__ import annotations

import os
from datetime import date, datetime
from typing import Dict, List, Tuple

from packages.core.dtos import EvidenceCandidate
from packages.retrieval.base import IVectorRetriever


class HybridRetriever(IVectorRetriever):
    def __init__(self, *, vector_retriever: IVectorRetriever, fts_retriever: IVectorRetriever) -> None:
        self._vector = vector_retriever
        self._fts = fts_retriever

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        value = os.getenv(name)
        if value is None or not value.strip():
            return default
        try:
            return float(value)
        except ValueError:
            return default

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

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

    @staticmethod
    def _parse_effective_date(raw: object | None) -> datetime | None:
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, date):
            return datetime.combine(raw, datetime.min.time())
        value = str(raw).strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _compute_final_scores(
        self,
        *,
        merged: Dict[Tuple[str, str], EvidenceCandidate],
        vector_norm: Dict[Tuple[str, str], float],
        fts_norm: Dict[Tuple[str, str], float],
    ) -> List[EvidenceCandidate]:
        vector_w = self._env_float("HYBRID_VECTOR_WEIGHT", 0.45)
        fts_w = self._env_float("HYBRID_FTS_WEIGHT", 0.35)
        authority_w = self._env_float("HYBRID_AUTHORITY_WEIGHT", 0.15)
        recency_w = self._env_float("HYBRID_RECENCY_WEIGHT", 0.05)

        # Keep weight scale stable even if env overrides are imbalanced.
        total_w = vector_w + fts_w + authority_w + recency_w
        if total_w <= 0:
            vector_w, fts_w, authority_w, recency_w = 0.45, 0.35, 0.15, 0.05
            total_w = 1.0
        vector_w /= total_w
        fts_w /= total_w
        authority_w /= total_w
        recency_w /= total_w

        max_authority = 1.0
        for candidate in merged.values():
            md = candidate.metadata or {}
            max_authority = max(max_authority, float(md.get("authority_level") or 0.0))

        recency_values: Dict[Tuple[str, str], float] = {}
        for key, candidate in merged.items():
            eff_dt = self._parse_effective_date((candidate.metadata or {}).get("effective_date"))
            recency_values[key] = eff_dt.timestamp() if eff_dt else 0.0

        if recency_values:
            min_ts = min(recency_values.values())
            max_ts = max(recency_values.values())
        else:
            min_ts = 0.0
            max_ts = 0.0

        final: List[EvidenceCandidate] = []
        for key, candidate in merged.items():
            md = dict(candidate.metadata or {})

            vector_score = self._clamp01(vector_norm.get(key, 0.0))
            fts_score = self._clamp01(fts_norm.get(key, 0.0))

            authority_level = float(md.get("authority_level") or 0.0)
            authority_weight = self._clamp01(authority_level / max_authority) if max_authority > 0 else 0.0

            if max_ts > min_ts:
                recency_weight = self._clamp01((recency_values.get(key, 0.0) - min_ts) / (max_ts - min_ts))
            else:
                recency_weight = 0.0

            final_score = (
                (vector_w * vector_score)
                + (fts_w * fts_score)
                + (authority_w * authority_weight)
                + (recency_w * recency_weight)
            )

            md["retriever"] = "hybrid"
            md["vector_score"] = vector_score
            md["fts_score"] = fts_score
            md["authority_weight"] = authority_weight
            md["recency_weight"] = recency_weight
            md["final_score"] = float(final_score)

            if vector_score >= fts_score and vector_score > 0:
                md["retriever_source"] = "pgvector"
            elif fts_score > 0:
                md["retriever_source"] = "pgsql_fts"
            else:
                md["retriever_source"] = candidate.source

            final.append(
                candidate.model_copy(
                    update={
                        "score": float(final_score),
                        "source": "hybrid",
                        "metadata": md,
                    }
                )
            )
        return final

    @staticmethod
    def _cap_per_policy(candidates: List[EvidenceCandidate], max_per_policy: int = 2) -> List[EvidenceCandidate]:
        """Phase 2.7 spec: cap to N sections per policy_id (not per version)."""
        if max_per_policy < 1:
            return candidates
        kept: List[EvidenceCandidate] = []
        counts: Dict[str, int] = {}
        for candidate in candidates:
            key = str(candidate.policy_id)
            current = counts.get(key, 0)
            if current >= max_per_policy:
                continue
            counts[key] = current + 1
            kept.append(candidate)
        return kept

    def retrieve(self, *, tenant_id, query: str, scope=None, user=None, top_k: int = 10) -> List[EvidenceCandidate]:
        # Per-source fetch count: spec calls for top 20 FTS + top 20 vector; configurable.
        source_top_k = max(1, int(os.getenv("HYBRID_SOURCE_TOP_K", "20") or "20"))
        vector_min_similarity = self._env_float("HYBRID_VECTOR_MIN_SIMILARITY", 0.65)
        fts_min_score = self._env_float("HYBRID_FTS_MIN_SCORE", 0.05)

        vector_raw = self._vector.retrieve(tenant_id=tenant_id, query=query, scope=scope, user=user, top_k=source_top_k)
        fts_raw = self._fts.retrieve(tenant_id=tenant_id, query=query, scope=scope, user=user, top_k=source_top_k)

        vector_results = [item for item in vector_raw if float(item.score or 0.0) >= vector_min_similarity]
        fts_results = [item for item in fts_raw if float(item.score or 0.0) >= fts_min_score]

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

        final = self._compute_final_scores(merged=merged, vector_norm=vector_norm, fts_norm=fts_norm)
        final.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        before_cap = len(final)
        final = self._cap_per_policy(final, max_per_policy=2)

        selected = final[: max(1, int(top_k))]
        debug_meta = {
            "hybrid_vector_candidates": len(vector_results),
            "hybrid_fts_candidates": len(fts_results),
            "hybrid_merged_candidates": len(merged),
            "hybrid_filtered_candidates": before_cap,
        }
        for item in selected:
            md = dict(item.metadata or {})
            md.update(debug_meta)
            item.metadata = md
        return selected
