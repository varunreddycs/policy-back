from __future__ import annotations

import os
from datetime import date, datetime

from packages.core.dtos import EvidenceCandidate
from packages.retrieval.base import IVectorRetriever


class HybridRetriever(IVectorRetriever):
    def __init__(
        self, *, vector_retriever: IVectorRetriever, fts_retriever: IVectorRetriever
    ) -> None:
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
    def _normalize(candidates: list[EvidenceCandidate]) -> dict[tuple[str, str], float]:
        if not candidates:
            return {}
        max_score = max(float(candidate.score or 0.0) for candidate in candidates)
        if max_score <= 0:
            return {
                (str(candidate.section_id or ""), str(candidate.policy_version_id)): 0.0
                for candidate in candidates
            }
        return {
            (str(candidate.section_id or ""), str(candidate.policy_version_id)): float(
                candidate.score or 0.0
            )
            / max_score
            for candidate in candidates
        }

    @staticmethod
    def _rank_map(candidates: list[EvidenceCandidate]) -> dict[tuple[str, str], int]:
        """1-based rank per source, highest score first.

        RRF consumes ranks rather than scores, which is the point: a rank is
        comparable across sources whose score scales are unrelated (cosine
        similarity vs ts_rank), whereas max-normalized scores are not.
        """
        ordered = sorted(candidates, key=lambda c: float(c.score or 0.0), reverse=True)
        return {
            (str(c.section_id or ""), str(c.policy_version_id)): position
            for position, c in enumerate(ordered, start=1)
        }

    @staticmethod
    def _rrf_contribution(rank: int | None, k: float) -> float:
        """Reciprocal Rank Fusion term: 1/(k + rank). Absent from a source = 0."""
        if rank is None:
            return 0.0
        return 1.0 / (k + float(rank))

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

    def _compute_rrf_scores(
        self,
        *,
        merged: dict[tuple[str, str], EvidenceCandidate],
        vector_ranks: dict[tuple[str, str], int],
        fts_ranks: dict[tuple[str, str], int],
        vector_sim: dict[tuple[str, str], float],
        fts_raw: dict[tuple[str, str], float],
    ) -> list[EvidenceCandidate]:
        """Rank-based Reciprocal Rank Fusion.

        Replaces max-normalization + linear weighting, whose output was
        batch-relative: the top candidate always normalized to 1.0 regardless of
        how well it actually matched, so the fused score trended to the weight
        ceiling and meant something different from a true cosine similarity.

        Governance signals (authority, recency) are blended into a reserved
        share of the range rather than summed in, so they can break near-ties
        without any candidate clipping at 1.0.
        """
        k = self._env_float("HYBRID_RRF_K", 60.0)
        vector_w = self._env_float("HYBRID_VECTOR_WEIGHT", 0.45)
        fts_w = self._env_float("HYBRID_FTS_WEIGHT", 0.35)
        authority_w = self._env_float("HYBRID_AUTHORITY_WEIGHT", 0.15)
        recency_w = self._env_float("HYBRID_RECENCY_WEIGHT", 0.05)

        if vector_w + fts_w <= 0:
            vector_w, fts_w = 0.45, 0.35

        max_authority = 1.0
        for candidate in merged.values():
            md = candidate.metadata or {}
            max_authority = max(max_authority, float(md.get("authority_level") or 0.0))

        recency_values: dict[tuple[str, str], float] = {}
        for key, candidate in merged.items():
            eff_dt = self._parse_effective_date(
                (candidate.metadata or {}).get("effective_date")
            )
            recency_values[key] = eff_dt.timestamp() if eff_dt else 0.0

        min_ts = min(recency_values.values()) if recency_values else 0.0
        max_ts = max(recency_values.values()) if recency_values else 0.0

        # Normalize RRF output to 0-1 against the best achievable term so the
        # fused score stays on a readable scale.
        best_possible = (vector_w + fts_w) / (k + 1.0)

        # Share of the 0-1 range the governance signals get to move a candidate.
        # RRF terms for adjacent ranks differ by ~1e-5, so without a reserved
        # band authority/recency would never break a near-tie.
        governance_span = max(0.0, min(0.9, authority_w + recency_w))

        final: list[EvidenceCandidate] = []
        for key, candidate in merged.items():
            md = dict(candidate.metadata or {})

            v_rank = vector_ranks.get(key)
            f_rank = fts_ranks.get(key)
            rrf = (vector_w * self._rrf_contribution(v_rank, k)) + (
                fts_w * self._rrf_contribution(f_rank, k)
            )
            rrf_norm = self._clamp01(rrf / best_possible) if best_possible > 0 else 0.0

            authority_level = float(md.get("authority_level") or 0.0)
            authority_weight = (
                self._clamp01(authority_level / max_authority)
                if max_authority > 0
                else 0.0
            )

            if max_ts > min_ts:
                recency_weight = self._clamp01(
                    (recency_values.get(key, 0.0) - min_ts) / (max_ts - min_ts)
                )
            else:
                recency_weight = 0.0

            # Blend rather than add: a plain sum saturates past 1.0, and
            # clamping there would flatten exactly the ordering the governance
            # signals exist to break. Reserving them a fixed share of the range
            # keeps every score inside 0-1 with no clipping.
            if governance_span > 0:
                governance = (
                    (authority_w * authority_weight) + (recency_w * recency_weight)
                ) / governance_span
                final_score = self._clamp01(
                    (1.0 - governance_span) * rrf_norm + governance_span * governance
                )
            else:
                final_score = self._clamp01(rrf_norm)

            md["retriever"] = "hybrid"
            md["fusion"] = "rrf"
            md["rrf_score"] = float(rrf_norm)
            md["vector_rank"] = v_rank
            md["fts_rank"] = f_rank
            md["authority_weight"] = authority_weight
            md["recency_weight"] = recency_weight
            md["final_score"] = float(final_score)

            # Q5: carry the TRUE per-source similarity so a calibrated absolute
            # threshold has something real to compare against. The fused score
            # is batch-relative and must not be used as a confidence measure.
            similarity = vector_sim.get(key)
            if similarity is not None:
                md["vector_similarity"] = float(similarity)
            fts_score_raw = fts_raw.get(key)
            if fts_score_raw is not None:
                md["fts_rank_score"] = float(fts_score_raw)

            if v_rank is not None and (f_rank is None or v_rank <= f_rank):
                md["retriever_source"] = "pgvector"
            elif f_rank is not None:
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

    def _compute_final_scores(
        self,
        *,
        merged: dict[tuple[str, str], EvidenceCandidate],
        vector_norm: dict[tuple[str, str], float],
        fts_norm: dict[tuple[str, str], float],
    ) -> list[EvidenceCandidate]:
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

        recency_values: dict[tuple[str, str], float] = {}
        for key, candidate in merged.items():
            eff_dt = self._parse_effective_date(
                (candidate.metadata or {}).get("effective_date")
            )
            recency_values[key] = eff_dt.timestamp() if eff_dt else 0.0

        if recency_values:
            min_ts = min(recency_values.values())
            max_ts = max(recency_values.values())
        else:
            min_ts = 0.0
            max_ts = 0.0

        final: list[EvidenceCandidate] = []
        for key, candidate in merged.items():
            md = dict(candidate.metadata or {})

            vector_score = self._clamp01(vector_norm.get(key, 0.0))
            fts_score = self._clamp01(fts_norm.get(key, 0.0))

            authority_level = float(md.get("authority_level") or 0.0)
            authority_weight = (
                self._clamp01(authority_level / max_authority)
                if max_authority > 0
                else 0.0
            )

            if max_ts > min_ts:
                recency_weight = self._clamp01(
                    (recency_values.get(key, 0.0) - min_ts) / (max_ts - min_ts)
                )
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
    def _cap_per_policy(
        candidates: list[EvidenceCandidate], max_per_policy: int = 2
    ) -> list[EvidenceCandidate]:
        """Phase 2.7 spec: cap to N sections per policy_id (not per version)."""
        if max_per_policy < 1:
            return candidates
        kept: list[EvidenceCandidate] = []
        counts: dict[str, int] = {}
        for candidate in candidates:
            key = str(candidate.policy_id)
            current = counts.get(key, 0)
            if current >= max_per_policy:
                continue
            counts[key] = current + 1
            kept.append(candidate)
        return kept

    def retrieve(
        self, *, tenant_id, query: str, scope=None, user=None, top_k: int = 10
    ) -> list[EvidenceCandidate]:
        # Per-source fetch count: spec calls for top 20 FTS + top 20 vector; configurable.
        source_top_k = max(1, int(os.getenv("HYBRID_SOURCE_TOP_K", "20") or "20"))
        vector_min_similarity = self._env_float("HYBRID_VECTOR_MIN_SIMILARITY", 0.65)
        fts_min_score = self._env_float("HYBRID_FTS_MIN_SCORE", 0.05)

        vector_raw = self._vector.retrieve(
            tenant_id=tenant_id, query=query, scope=scope, user=user, top_k=source_top_k
        )
        fts_raw = self._fts.retrieve(
            tenant_id=tenant_id, query=query, scope=scope, user=user, top_k=source_top_k
        )

        vector_results = [
            item
            for item in vector_raw
            if float(item.score or 0.0) >= vector_min_similarity
        ]
        fts_results = [
            item for item in fts_raw if float(item.score or 0.0) >= fts_min_score
        ]

        fusion_mode = os.getenv("HYBRID_FUSION", "rrf").strip().lower()

        vector_norm = self._normalize(vector_results)
        fts_norm = self._normalize(fts_results)

        # True per-source scores, kept for the calibrated refusal gate (Q5).
        vector_sim = {
            (str(c.section_id or ""), str(c.policy_version_id)): float(c.score or 0.0)
            for c in vector_results
        }
        fts_raw_scores = {
            (str(c.section_id or ""), str(c.policy_version_id)): float(c.score or 0.0)
            for c in fts_results
        }

        merged: dict[tuple[str, str], EvidenceCandidate] = {}

        for candidate in vector_results:
            key = (str(candidate.section_id or ""), str(candidate.policy_version_id))
            merged[key] = candidate.model_copy(deep=True)

        for candidate in fts_results:
            key = (str(candidate.section_id or ""), str(candidate.policy_version_id))
            if key not in merged:
                merged[key] = candidate.model_copy(deep=True)

        if fusion_mode == "linear":
            final = self._compute_final_scores(
                merged=merged, vector_norm=vector_norm, fts_norm=fts_norm
            )
        else:
            final = self._compute_rrf_scores(
                merged=merged,
                vector_ranks=self._rank_map(vector_results),
                fts_ranks=self._rank_map(fts_results),
                vector_sim=vector_sim,
                fts_raw=fts_raw_scores,
            )
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
