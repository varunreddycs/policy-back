from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import Depends
from sqlalchemy.orm import Session

from packages.db.session import get_db_session
from packages.db.repositories.factory import RepositorySet, build_repositories
from packages.governance.audit_service import AuditService
from packages.rag.ask_service import AskService
from packages.retrieval.factory import build_retriever
from packages.db.policy_query_service import PolicyQueryService
from packages.ingestion.ingestion_service import IngestionService
from packages.queue.queue_service import QueueService
from packages.storage.blob_service import BlobService

_DB_BACKEND = os.getenv("DB_BACKEND", "postgresql").strip().lower()
_COSMOS_DATABASE = os.getenv("COSMOS_DATABASE", "policydb")


@lru_cache
def _cosmos_client() -> Any:
    from packages.db.repositories.cosmos.cosmos_client_factory import create_cosmos_client
    return create_cosmos_client()


@lru_cache
def _cosmos_containers() -> Any:
    from packages.db.repositories.cosmos.cosmos_client_factory import get_or_create_containers
    return get_or_create_containers(_cosmos_client(), _COSMOS_DATABASE)


def get_db(session: Session | None = Depends(get_db_session)) -> Session | None:
    return session


@lru_cache
def get_blob_service() -> BlobService:
    return BlobService()


@lru_cache
def get_queue_service() -> QueueService:
    return QueueService.from_env()


def get_repositories(session: Session | None = Depends(get_db)) -> RepositorySet:
    if _DB_BACKEND == "cosmos":
        return build_repositories(
            backend="cosmos",
            cosmos_client=_cosmos_client(),
            cosmos_database=_COSMOS_DATABASE,
        )
    return build_repositories(session=session)


def get_ingestion_service(
    session: Session | None = Depends(get_db),
    blob_service: BlobService = Depends(get_blob_service),
    queue_service: QueueService = Depends(get_queue_service),
) -> IngestionService:
    return IngestionService(session=session, blob_service=blob_service, queue_service=queue_service)


def get_policy_query_service(repos: RepositorySet = Depends(get_repositories)) -> PolicyQueryService:
    return PolicyQueryService(repos=repos)


def get_ask_service(
    session: Session | None = Depends(get_db),
    repos: RepositorySet = Depends(get_repositories),
) -> AskService:
    if _DB_BACKEND == "cosmos":
        retriever = build_retriever(cosmos_containers=_cosmos_containers())
        return AskService(retriever=retriever, audit_repo=repos.audit)
    retriever = build_retriever(session=session)
    return AskService(session=session, retriever=retriever)


def get_audit_service(repos: RepositorySet = Depends(get_repositories)) -> AuditService:
    return AuditService(audit_repo=repos.audit)
