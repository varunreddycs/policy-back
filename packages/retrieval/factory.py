from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from packages.retrieval.base import IVectorRetriever
from packages.retrieval.hybrid_provider import HybridRetriever
from packages.retrieval.pgsql_fts_provider import PgsqlFtsRetriever
from packages.retrieval.pgvector_provider import PgVectorRetriever


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _has_embedding_config() -> bool:
    required = [
        os.getenv("AZURE_OPENAI_ENDPOINT"),
        os.getenv("AZURE_OPENAI_API_KEY"),
        os.getenv("AZURE_OPENAI_API_VERSION"),
        os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"),
    ]
    return all(bool(item and str(item).strip()) for item in required)


def build_retriever(
    *,
    session: "Session | None" = None,
    cosmos_containers: "Any | None" = None,
) -> IVectorRetriever:
    db_backend = os.getenv("DB_BACKEND", "postgresql").strip().lower()

    # Cosmos DB NoSQL backend
    if db_backend == "cosmos":
        from packages.retrieval.cosmos_vector_provider import CosmosVectorRetriever

        if cosmos_containers is None:
            from packages.db.repositories.cosmos.cosmos_client_factory import (
                create_cosmos_client,
                get_or_create_containers,
            )
            client = create_cosmos_client()
            cosmos_containers = get_or_create_containers(
                client, os.getenv("COSMOS_DATABASE", "policydb")
            )
        return CosmosVectorRetriever(
            embeddings_container=cosmos_containers.embeddings,
            policies_container=cosmos_containers.policies,
            sections_container=cosmos_containers.sections,
            default_top_k=max(1, _env_int("EMBEDDINGS_TOP_K", 40)),
        )

    # PostgreSQL backend (default)
    if session is None:
        raise ValueError("PostgreSQL retriever backend requires a SQLAlchemy session")

    backend = os.getenv("RETRIEVER_BACKEND", "pgsql_fts").strip().lower()
    embeddings_enabled = _env_bool("EMBEDDINGS_ENABLED", True)
    if embeddings_enabled and not _has_embedding_config():
        embeddings_enabled = False
    embeddings_top_k = max(1, _env_int("EMBEDDINGS_TOP_K", 40))
    fts_top_k = max(1, _env_int("FTS_TOP_K", 40))

    fts_retriever = PgsqlFtsRetriever(session=session, default_top_k=fts_top_k)
    vector_retriever = PgVectorRetriever(session=session, default_top_k=embeddings_top_k)

    if backend == "pgvector":
        return vector_retriever if embeddings_enabled else fts_retriever

    if backend == "hybrid":
        if not embeddings_enabled:
            return fts_retriever
        return HybridRetriever(vector_retriever=vector_retriever, fts_retriever=fts_retriever)

    # default: pgsql_fts
    return fts_retriever
