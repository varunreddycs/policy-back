from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from packages.db.session import get_db_session
from packages.governance.audit_service import AuditService
from packages.rag.ask_service import AskService
from packages.retrieval.factory import build_retriever
from packages.db.policy_query_service import PolicyQueryService
from packages.ingestion.ingestion_service import IngestionService
from packages.queue.queue_service import QueueService
from packages.storage.blob_service import BlobService


def db_session_dep() -> Session:
    raise RuntimeError("Use get_db_session dependency")


def get_db(session=Depends(get_db_session)) -> Session:
    return session


@lru_cache
def get_blob_service() -> BlobService:
    return BlobService()


@lru_cache
def get_queue_service() -> QueueService:
    return QueueService.from_env()


def get_ingestion_service(
    session: Session = Depends(get_db),
    blob_service: BlobService = Depends(get_blob_service),
    queue_service: QueueService = Depends(get_queue_service),
) -> IngestionService:
    return IngestionService(session=session, blob_service=blob_service, queue_service=queue_service)


def get_policy_query_service(session: Session = Depends(get_db)) -> PolicyQueryService:
    return PolicyQueryService(session=session)


def get_ask_service(session: Session = Depends(get_db)) -> AskService:
    retriever = build_retriever(session=session)
    return AskService(session=session, retriever=retriever)


def get_audit_service(session: Session = Depends(get_db)) -> AuditService:
    return AuditService(session=session)
