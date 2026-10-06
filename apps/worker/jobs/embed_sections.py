"""Backend-agnostic embedding of a single policy version's sections.

This is the shared core the auto-embed-on-ingest path calls after the worker
persists a version's sections. It works against any repository backend
(PostgreSQL, Cosmos) via ``RepositorySet`` — no raw SQL or Cosmos SDK calls.

Idempotency: embeddings for the version are deleted before re-insert, so a
retried worker message never leaves duplicate rows. Reuses the embedding text
formatting and model-name logic from :mod:`apps.worker.jobs.embed_backfill`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from apps.worker.jobs.embed_backfill import _embedding_model_name, format_embedding_text
from packages.db.repositories.factory import RepositorySet
from packages.db.repositories.repo_dtos import (
    PolicyDTO,
    PolicySectionDTO,
    PolicyVersionDTO,
)
from packages.embeddings.azure_openai_client import embed_texts
from packages.embeddings.config import has_embedding_config

logger = logging.getLogger(__name__)

Embedder = Callable[[list[str]], list[list[float]]]

_SECTION_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class EmbedResult:
    """Outcome of an auto-embed run for one version."""

    embedded: int
    skipped_reason: str | None = None


def _all_sections_for_version(
    repos: RepositorySet,
    *,
    tenant_id,
    policy_version_id,
) -> list[PolicySectionDTO]:
    out: list[PolicySectionDTO] = []
    offset = 0
    while True:
        batch = repos.sections.list_for_version(
            tenant_id=tenant_id,
            policy_version_id=policy_version_id,
            limit=_SECTION_PAGE_SIZE,
            offset=offset,
        )
        out.extend(batch)
        if len(batch) < _SECTION_PAGE_SIZE:
            break
        offset += _SECTION_PAGE_SIZE
    return out


def embed_sections_for_version(
    *,
    repos: RepositorySet,
    policy: PolicyDTO,
    version: PolicyVersionDTO,
    embedder: Embedder | None = None,
    correlation_id: str | None = None,
) -> EmbedResult:
    """Embed every section of *version* into the vector store via *repos*.

    Skips cleanly (no exception) when Azure OpenAI embedding config is absent.
    Deletes existing embeddings for the version first so retries are idempotent.
    Callers own the transaction: this only issues repository writes and does not
    commit.

    When *embedder* is ``None`` the module-level ``embed_texts`` is resolved at
    call time (so tests can monkeypatch it on this module).
    """
    embed = embedder if embedder is not None else embed_texts
    if not has_embedding_config():
        logger.warning(
            "worker.auto_embed_skipped_no_config",
            extra={
                "policy_version_id": str(version.id),
                "correlation_id": correlation_id,
            },
        )
        return EmbedResult(embedded=0, skipped_reason="missing_embedding_config")

    sections = _all_sections_for_version(
        repos, tenant_id=version.tenant_id, policy_version_id=version.id
    )
    if not sections:
        return EmbedResult(embedded=0, skipped_reason="no_sections")

    texts = [
        format_embedding_text(
            policy_type=policy.policy_type,
            department_scope=policy.department_scope,
            authority_level=policy.authority_level,
            title=section.title,
            section_text=section.text,
        )
        for section in sections
    ]
    vectors = embed(texts)
    if len(vectors) != len(sections):
        raise RuntimeError(
            f"Embedding count mismatch: {len(vectors)} vectors for {len(sections)} sections"
        )

    embedding_model = _embedding_model_name()

    # Delete-then-insert keeps retries idempotent across both backends (the PG
    # bulk_insert has no ON CONFLICT handling, and Cosmos upserts on a fresh id).
    repos.embeddings.delete_for_version(policy_version_id=version.id)
    embedding_dicts = [
        {
            "tenant_id": version.tenant_id,
            "policy_version_id": version.id,
            "policy_section_id": section.id,
            "embedding_model": embedding_model,
            "embedding": vector,
            "content_sha256": section.content_sha256,
            "authority_level": policy.authority_level,
            "department_scope": policy.department_scope,
            "policy_type": policy.policy_type,
            "effective_date": version.effective_date,
        }
        for section, vector in zip(sections, vectors)
    ]
    inserted = repos.embeddings.bulk_insert(embedding_dicts)
    logger.info(
        "worker.auto_embed_completed",
        extra={
            "policy_version_id": str(version.id),
            "policy_id": str(policy.id),
            "sections": len(sections),
            "embeddings_inserted": inserted,
            "embedding_model": embedding_model,
            "correlation_id": correlation_id,
        },
    )
    return EmbedResult(embedded=inserted)
