from __future__ import annotations

import argparse
import os
import uuid
from dataclasses import dataclass
from typing import Callable, List

from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

from packages.db.models.policy_models import ParseStatus, Policy, PolicyEmbedding, PolicySection, PolicyVersion
from packages.db.session import get_sessionmaker
from packages.embeddings.azure_openai_client import embed_texts


Embedder = Callable[[List[str]], List[List[float]]]


def _embedding_model_name() -> str:
    return os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "azure-openai-embeddings")


def format_embedding_text(*, policy_type: str | None, department_scope: str | None, authority_level: int | None, title: str | None, section_text: str) -> str:
    return (
        f"Policy Type: {policy_type or 'unknown'}\n"
        f"Department Scope: {department_scope or 'all'}\n"
        f"Authority Level: {int(authority_level or 0)}\n"
        f"Section Title: {title or 'Untitled'}\n\n"
        f"{section_text or ''}"
    )


def _vector_literal(vector: List[float]) -> str:
    return "[" + ",".join(f"{float(value):.12g}" for value in vector) + "]"


@dataclass
class BackfillStats:
    scanned: int = 0
    inserted: int = 0


def _fetch_sections_batch(*, session: Session, tenant_id: uuid.UUID, only_current: bool, embedding_model: str, limit: int) -> list:
    join_condition = and_(
        PolicyEmbedding.policy_section_id == PolicySection.id,
        PolicyEmbedding.embedding_model == embedding_model,
    )

    stmt = (
        select(
            PolicySection.id.label("policy_section_id"),
            PolicySection.policy_version_id.label("policy_version_id"),
            PolicySection.content_sha256.label("content_sha256"),
            PolicySection.text.label("section_text"),
            PolicySection.title.label("section_title"),
            PolicyVersion.effective_date.label("effective_date"),
            Policy.authority_level.label("authority_level"),
            Policy.department_scope.label("department_scope"),
            Policy.policy_type.label("policy_type"),
        )
        .select_from(PolicySection)
        .join(PolicyVersion, PolicyVersion.id == PolicySection.policy_version_id)
        .join(Policy, Policy.id == PolicyVersion.policy_id)
        .outerjoin(PolicyEmbedding, join_condition)
        .where(PolicySection.tenant_id == tenant_id)
        .where(PolicyVersion.parse_status == ParseStatus.READY.value)
        .where(PolicyVersion.is_current.is_(True) if only_current else text("TRUE"))
        .where(PolicyEmbedding.id.is_(None))
        .order_by(PolicySection.created_at.asc())
        .limit(limit)
    )
    return list(session.execute(stmt).all())


def _insert_embeddings_batch(*, session: Session, tenant_id: uuid.UUID, embedding_model: str, rows: list, vectors: List[List[float]]) -> int:
    if not rows:
        return 0

    insert_sql = text(
        """
        INSERT INTO policy_embeddings (
            tenant_id,
            policy_version_id,
            policy_section_id,
            embedding_model,
            embedding,
            content_sha256,
            authority_level,
            department_scope,
            policy_type,
            effective_date
        )
        VALUES (
            :tenant_id,
            :policy_version_id,
            :policy_section_id,
            :embedding_model,
            CAST(:embedding AS vector),
            :content_sha256,
            :authority_level,
            :department_scope,
            :policy_type,
            :effective_date
        )
        ON CONFLICT (policy_section_id, embedding_model) DO NOTHING
        """
    )

    inserted = 0
    for row, vector in zip(rows, vectors):
        params = {
            "tenant_id": tenant_id,
            "policy_version_id": row.policy_version_id,
            "policy_section_id": row.policy_section_id,
            "embedding_model": embedding_model,
            "embedding": _vector_literal(vector),
            "content_sha256": row.content_sha256,
            "authority_level": row.authority_level,
            "department_scope": row.department_scope,
            "policy_type": row.policy_type,
            "effective_date": row.effective_date,
        }
        result = session.execute(insert_sql, params)
        rowcount = int(getattr(result, "rowcount", 0) or 0)
        inserted += max(0, rowcount)
    return inserted


def backfill_embeddings(*, session: Session, tenant_id: uuid.UUID, only_current: bool = True, batch_size: int = 64, embedder: Embedder = embed_texts) -> BackfillStats:
    stats = BackfillStats()
    embedding_model = _embedding_model_name()

    while True:
        rows = _fetch_sections_batch(
            session=session,
            tenant_id=tenant_id,
            only_current=only_current,
            embedding_model=embedding_model,
            limit=batch_size,
        )
        if not rows:
            session.commit()
            return stats

        texts = [
            format_embedding_text(
                policy_type=row.policy_type,
                department_scope=row.department_scope,
                authority_level=row.authority_level,
                title=row.section_title,
                section_text=row.section_text,
            )
            for row in rows
        ]
        vectors = embedder(texts)
        if len(vectors) != len(rows):
            raise RuntimeError("Embedding count mismatch for backfill batch")

        stats.scanned += len(rows)
        stats.inserted += _insert_embeddings_batch(
            session=session,
            tenant_id=tenant_id,
            embedding_model=embedding_model,
            rows=rows,
            vectors=vectors,
        )
        session.commit()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill policy section embeddings")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID")
    parser.add_argument("--only-current", action="store_true", help="Embed only current policy versions")
    parser.add_argument("--batch-size", type=int, default=64)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    tenant_id = uuid.UUID(args.tenant_id)
    SessionLocal = get_sessionmaker()

    with SessionLocal() as session:
        stats = backfill_embeddings(
            session=session,
            tenant_id=tenant_id,
            only_current=bool(args.only_current),
            batch_size=max(1, int(args.batch_size)),
        )
    print({"scanned": stats.scanned, "inserted": stats.inserted})


if __name__ == "__main__":
    main()
