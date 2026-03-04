from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import create_engine, text

from .config import Settings


logger = logging.getLogger("ohio_docs_ingestor.verify")


@dataclass
class BatchCounts:
    registered: int
    processing: int
    ready: int
    failed: int


def _get_engine(settings: Settings):
    if not settings.database_url:
        return None
    return create_engine(settings.database_url, future=True)


def get_batch_counts(settings: Settings, *, batch_id: str, tenant_id: str) -> BatchCounts:
    engine = _get_engine(settings)
    if engine is None:
        return BatchCounts(registered=0, processing=0, ready=0, failed=0)

    sql = text(
        """
        SELECT
          COUNT(*)::int AS registered,
          SUM(CASE WHEN parse_status IN ('pending','received','queued','processing') THEN 1 ELSE 0 END)::int AS processing,
          SUM(CASE WHEN parse_status IN ('ready','parsed') THEN 1 ELSE 0 END)::int AS ready,
          SUM(CASE WHEN parse_status IN ('failed','cancelled') THEN 1 ELSE 0 END)::int AS failed
        FROM policy_versions
        WHERE tenant_id = :tenant_id::uuid AND ingest_batch_id = :batch_id::uuid
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"tenant_id": tenant_id, "batch_id": batch_id}).mappings().first()
    if not row:
        return BatchCounts(registered=0, processing=0, ready=0, failed=0)
    return BatchCounts(
        registered=int(row["registered"] or 0),
        processing=int(row["processing"] or 0),
        ready=int(row["ready"] or 0),
        failed=int(row["failed"] or 0),
    )


def get_embedding_counts(settings: Settings, *, tenant_id: str) -> dict[str, int]:
    engine = _get_engine(settings)
    if engine is None:
        return {"policy_sections": 0, "policy_embeddings": 0}

    sections_sql = text(
        """
        SELECT COUNT(*)::int AS c
        FROM policy_sections
        WHERE tenant_id = :tenant_id::uuid
        """
    )
    embeddings_sql = text(
        """
        SELECT COUNT(*)::int AS c
        FROM policy_embeddings
        WHERE tenant_id = :tenant_id::uuid
        """
    )
    with engine.connect() as conn:
        sections = int(conn.execute(sections_sql, {"tenant_id": tenant_id}).scalar_one())
        embeddings = int(conn.execute(embeddings_sql, {"tenant_id": tenant_id}).scalar_one())
    return {"policy_sections": sections, "policy_embeddings": embeddings}


def wait_for_batch_completion(settings: Settings, *, api_client, batch_id: str, tenant_id: str) -> dict:
    started = time.time()
    while True:
        batch = api_client.get_batch(batch_id=batch_id)
        counts = get_batch_counts(settings, batch_id=batch_id, tenant_id=tenant_id)

        logger.info(
            "batch.progress",
            extra={
                "extra_fields": {
                    "batch_id": batch_id,
                    "batch_status": batch.get("status"),
                    "registered": counts.registered,
                    "processing": counts.processing,
                    "ready": counts.ready,
                    "failed": counts.failed,
                }
            },
        )

        done = counts.registered > 0 and (counts.ready + counts.failed) >= counts.registered
        if done:
            return {
                "batch": batch,
                "counts": {
                    "registered": counts.registered,
                    "processing": counts.processing,
                    "ready": counts.ready,
                    "failed": counts.failed,
                },
                "timed_out": False,
            }

        elapsed = time.time() - started
        if elapsed >= settings.poll_timeout_seconds:
            return {
                "batch": batch,
                "counts": {
                    "registered": counts.registered,
                    "processing": counts.processing,
                    "ready": counts.ready,
                    "failed": counts.failed,
                },
                "timed_out": True,
            }

        time.sleep(settings.poll_interval_seconds)
