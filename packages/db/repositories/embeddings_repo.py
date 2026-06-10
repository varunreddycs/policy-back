"""PostgreSQL implementation of IEmbeddingRepository."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from sqlalchemy import delete
from sqlalchemy.orm import Session

from packages.db.models.policy_models import PolicyEmbedding
from packages.db.repositories.base import IEmbeddingRepository


class PgEmbeddingRepository(IEmbeddingRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def bulk_insert(self, embeddings: List[Dict[str, Any]]) -> int:
        count = 0
        for e in embeddings:
            self._session.add(PolicyEmbedding(**e))
            count += 1
        self._session.flush()
        return count

    def delete_for_version(self, *, policy_version_id: uuid.UUID) -> int:
        result = self._session.execute(
            delete(PolicyEmbedding).where(PolicyEmbedding.policy_version_id == policy_version_id)
        )
        return int(result.rowcount or 0)
