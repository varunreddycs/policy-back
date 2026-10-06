from __future__ import annotations

import os
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from packages.core.dtos import EvidenceCandidate
from packages.db.models.policy_models import ParseStatus
from packages.embeddings.azure_openai_client import embed_texts
from packages.retrieval.base import IVectorRetriever
from packages.retrieval.control_ids import normalize_control_ids


class PgVectorRetriever(IVectorRetriever):
    """pgvector retriever."""

    def __init__(
        self,
        *,
        session: Session,
        embedder=embed_texts,
        default_top_k: int | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder
        env_top_k = int(os.getenv("EMBEDDINGS_TOP_K", "40"))
        self._default_top_k = max(1, int(default_top_k or env_top_k))

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        return "[" + ",".join(f"{float(value):.12g}" for value in vector) + "]"

    def retrieve(
        self, *, tenant_id: UUID, query: str, scope=None, user=None, top_k: int = 10
    ) -> list[EvidenceCandidate]:
        q = (query or "").strip()
        if not q:
            return []

        # Q7: canonicalize control IDs before embedding so "ac-02" and "AC-2"
        # produce the same vector as the form used in the corpus.
        vectors = self._embedder([normalize_control_ids(q)])
        if not vectors:
            return []
        query_vector = self._vector_literal(vectors[0])

        only_current = True
        policy_ids = None
        policy_types = None
        as_of = None
        if scope is not None:
            only_current = bool(getattr(scope, "only_current", True))
            policy_ids = getattr(scope, "policy_ids", None)
            policy_types = getattr(scope, "policy_types", None)
            as_of = getattr(scope, "as_of", None)

        user_department = (
            getattr(user, "department", None) if user is not None else None
        )
        limit_value = max(1, int(top_k or self._default_top_k))

        conditions = [
            "pe.tenant_id = :tenant_id",
            "pv.parse_status = :ready_status",
        ]
        params: dict = {
            "tenant_id": tenant_id,
            "ready_status": ParseStatus.READY.value,
            "query_vector": query_vector,
            "limit": limit_value,
        }

        if as_of is not None:
            # S2: pin to the version authoritative on the requested date — the
            # latest READY version effective on or before it (created_at::date is
            # the fallback for undated versions, version_number breaks same-day
            # ties). Replaces is_current, which answers a different question.
            conditions.append(
                "COALESCE(pv.effective_date, pv.created_at::date) <= :as_of"
            )
            conditions.append(
                """NOT EXISTS (
					SELECT 1 FROM policy_versions newer
					WHERE newer.policy_id = pv.policy_id
					  AND newer.parse_status = :ready_status
					  AND COALESCE(newer.effective_date, newer.created_at::date) <= :as_of
					  AND (
						COALESCE(newer.effective_date, newer.created_at::date)
						  > COALESCE(pv.effective_date, pv.created_at::date)
						OR (
						  COALESCE(newer.effective_date, newer.created_at::date)
							= COALESCE(pv.effective_date, pv.created_at::date)
						  AND newer.version_number > pv.version_number
						)
					  )
				)"""
            )
            params["as_of"] = as_of
        elif only_current:
            conditions.append("pv.is_current = TRUE")
        if policy_ids:
            conditions.append("p.id = ANY(:policy_ids)")
            params["policy_ids"] = list(policy_ids)
        if policy_types:
            conditions.append("p.policy_type = ANY(:policy_types)")
            params["policy_types"] = [str(item) for item in policy_types]

        sql = text(
            f"""
			SELECT
				p.id AS policy_id,
				p.name AS policy_name,
				pv.id AS policy_version_id,
				ps.id AS section_id,
				ps.text AS section_text,
				ps.section_path AS section_path,
				ps.title AS section_title,
				ps.section_index AS section_index,
				pv.is_current AS is_current,
				pv.version_label AS version_label,
				pv.effective_date AS effective_date,
				COALESCE(
					pv.metadata_json->>'source_url',
					pv.metadata_json->>'public_url',
					pv.metadata_json->>'url'
				) AS public_url,
				COALESCE(pe.authority_level, p.authority_level, 0) AS authority_level,
				COALESCE(pe.department_scope, p.department_scope, 'all') AS department_scope,
				COALESCE(pe.policy_type, p.policy_type) AS policy_type,
				((pe.embedding::halfvec(3072)) <=> CAST(:query_vector AS halfvec(3072))) AS distance
			FROM policy_embeddings pe
			JOIN policy_sections ps ON ps.id = pe.policy_section_id
			JOIN policy_versions pv ON pv.id = pe.policy_version_id
			JOIN policies p ON p.id = pv.policy_id
			WHERE {" AND ".join(conditions)}
			ORDER BY (pe.embedding::halfvec(3072)) <=> CAST(:query_vector AS halfvec(3072))
			LIMIT :limit
			"""
        )

        rows = self._session.execute(sql, params).all()
        results: list[EvidenceCandidate] = []
        for row in rows:
            distance = float(row.distance or 0.0)
            score = max(0.0, min(1.0, 1.0 - distance))
            results.append(
                EvidenceCandidate(
                    policy_id=row.policy_id,
                    policy_version_id=row.policy_version_id,
                    section_id=row.section_id,
                    text=row.section_text,
                    score=score,
                    source="pgvector",
                    metadata={
                        "section_path": row.section_path,
                        "title": row.section_title,
                        "policy_name": row.policy_name,
                        "public_url": row.public_url,
                        "section_index": int(row.section_index or 0),
                        "retriever": "pgvector",
                        "is_current": True
                        if as_of is not None
                        else bool(row.is_current),
                        "version_label": getattr(row, "version_label", None),
                        "as_of": as_of.isoformat() if as_of is not None else None,
                        "effective_date": (
                            row.effective_date.isoformat()
                            if row.effective_date
                            else None
                        ),
                        "authority_level": int(row.authority_level or 0),
                        "department_scope": str(row.department_scope or "all"),
                        "policy_type": row.policy_type,
                        "user_department": user_department,
                    },
                )
            )
        return results


# Back-compat alias (older name)
PgvectorRetriever = PgVectorRetriever
