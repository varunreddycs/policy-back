from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from db.session import get_db_session
from services import BlobService, IngestionService, QueueService
from services.policy_query_service import PolicyQueryService


def db_session_dep() -> Session:
    # For type checkers only; FastAPI uses generator dependency below.
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
