"""Cosmos DB client and container management.

Creates the database and containers on first use (idempotent).
Container partition keys and vector index policies are defined here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional


CONTAINER_DEFS = {
    "policies": {"partition_key": "/tenant_id"},
    "sections": {"partition_key": "/tenant_id"},
    "audit_logs": {"partition_key": "/tenant_id"},
    "embeddings": {
        "partition_key": "/tenant_id",
        "vector_embedding_policy": {
            "vectorEmbeddings": [
                {
                    "path": "/embedding",
                    "dataType": "float32",
                    "distanceFunction": "cosine",
                    "dimensions": 3072,
                }
            ]
        },
        "indexing_policy": {
            "vectorIndexes": [
                {"path": "/embedding", "type": "diskANN"}
            ]
        },
    },
    "references": {"partition_key": "/tenant_id"},
    "ingest_batches": {"partition_key": "/tenant_id"},
}


@dataclass(frozen=True, slots=True)
class CosmosContainers:
    policies: Any
    sections: Any
    audit_logs: Any
    embeddings: Any
    references: Any
    ingest_batches: Any


def create_cosmos_client():
    """Create a CosmosClient from environment variables."""
    try:
        from azure.cosmos import CosmosClient
    except ImportError as exc:
        raise ImportError(
            "azure-cosmos is required for Cosmos DB backend. Install with: pip install azure-cosmos"
        ) from exc

    endpoint = os.environ["COSMOS_ENDPOINT"]
    key = os.environ["COSMOS_KEY"]
    return CosmosClient(endpoint, credential=key)


def get_or_create_containers(
    cosmos_client: Any,
    database_name: str,
) -> CosmosContainers:
    """Ensure database and all containers exist (idempotent), return container proxies."""
    from azure.cosmos import PartitionKey

    db = cosmos_client.create_database_if_not_exists(id=database_name)

    containers = {}
    for name, spec in CONTAINER_DEFS.items():
        kwargs: dict[str, Any] = {
            "id": name,
            "partition_key": PartitionKey(path=spec["partition_key"]),
        }
        if "vector_embedding_policy" in spec:
            kwargs["vector_embedding_policy"] = spec["vector_embedding_policy"]
        if "indexing_policy" in spec:
            kwargs["indexing_policy"] = spec["indexing_policy"]

        containers[name] = db.create_container_if_not_exists(**kwargs)

    return CosmosContainers(
        policies=containers["policies"],
        sections=containers["sections"],
        audit_logs=containers["audit_logs"],
        embeddings=containers["embeddings"],
        references=containers["references"],
        ingest_batches=containers["ingest_batches"],
    )
