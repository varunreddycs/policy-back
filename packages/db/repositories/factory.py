"""Repository factory — returns the correct set of repositories for the configured DB backend.

Usage:
    repos = build_repositories(session=session)  # uses DB_BACKEND env var
    repos = build_repositories(session=session, backend="postgresql")
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from packages.db.repositories.base import (
    IAuditRepository,
    IEmbeddingRepository,
    IIngestBatchRepository,
    IIngestItemRepository,
    IPolicyRepository,
    IPolicySectionRepository,
    IPolicyVersionRepository,
    IReferenceRepository,
)


@dataclass(frozen=True, slots=True)
class RepositorySet:
    """All repository interfaces needed by the application, bundled for DI."""

    policies: IPolicyRepository
    versions: IPolicyVersionRepository
    sections: IPolicySectionRepository
    embeddings: IEmbeddingRepository
    audit: IAuditRepository
    ingest_batches: IIngestBatchRepository
    ingest_items: IIngestItemRepository
    references: IReferenceRepository


def build_repositories(
    *,
    backend: Optional[str] = None,
    # PostgreSQL
    session: Any = None,
    # Cosmos DB NoSQL
    cosmos_client: Any = None,
    cosmos_database: Optional[str] = None,
) -> RepositorySet:
    """Instantiate all repositories for the given backend.

    Parameters
    ----------
    backend : str, optional
        One of ``"postgresql"`` (default), ``"cosmos"``.
        Falls back to the ``DB_BACKEND`` env var.
    session : sqlalchemy.orm.Session, optional
        Required when backend is ``"postgresql"``.
    cosmos_client : azure.cosmos.CosmosClient, optional
        Required when backend is ``"cosmos"``.
    cosmos_database : str, optional
        Cosmos database name. Required when backend is ``"cosmos"``.
    """
    backend = (backend or os.getenv("DB_BACKEND", "postgresql")).strip().lower()

    if backend == "postgresql":
        if session is None:
            raise ValueError("PostgreSQL backend requires a SQLAlchemy session")
        return _build_pg(session)

    if backend == "cosmos":
        if cosmos_client is None:
            raise ValueError("Cosmos backend requires a CosmosClient instance")
        return _build_cosmos(cosmos_client, cosmos_database or os.getenv("COSMOS_DATABASE", "policydb"))

    raise ValueError(f"Unknown DB_BACKEND: {backend!r}. Supported: postgresql, cosmos")


def _build_pg(session: Any) -> RepositorySet:
    from packages.db.repositories.audit_repo import PgAuditRepository
    from packages.db.repositories.embeddings_repo import PgEmbeddingRepository
    from packages.db.repositories.ingestion_repo import PgIngestBatchRepository, PgIngestItemRepository
    from packages.db.repositories.policies_repo import PgPolicyRepository
    from packages.db.repositories.references_repo import PgReferenceRepository
    from packages.db.repositories.sections_repo import PgPolicySectionRepository
    from packages.db.repositories.versions_repo import PgPolicyVersionRepository

    return RepositorySet(
        policies=PgPolicyRepository(session),
        versions=PgPolicyVersionRepository(session),
        sections=PgPolicySectionRepository(session),
        embeddings=PgEmbeddingRepository(session),
        audit=PgAuditRepository(session),
        ingest_batches=PgIngestBatchRepository(session),
        ingest_items=PgIngestItemRepository(session),
        references=PgReferenceRepository(session),
    )


def _build_cosmos(cosmos_client: Any, database_name: str) -> RepositorySet:
    from packages.db.repositories.cosmos.cosmos_repos import build_cosmos_repos

    return build_cosmos_repos(cosmos_client=cosmos_client, database_name=database_name)
