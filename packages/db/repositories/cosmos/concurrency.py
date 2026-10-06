"""Optimistic concurrency for Cosmos read-modify-write cycles.

Several documents here carry nested arrays — versions inside a policy, items
inside an ingest batch — so appending one element means rewriting the whole
document. A bare ``upsert_item`` makes that last-write-wins: two writers read
the same array and the second silently discards the first one's element.

``rmw`` closes that by replaying the read-modify-write under an ``If-Match``
precondition and retrying when the document changed underneath.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Optional, TypeVar

from packages.db.repositories.errors import RepositoryConflict

T = TypeVar("T")

MAX_ATTEMPTS = 5
_BASE_BACKOFF_SECONDS = 0.02


def _is_precondition_failure(exc: BaseException) -> bool:
    """True when Cosmos rejected a write because the ETag no longer matched."""
    return getattr(exc, "status_code", None) == 412


def _write_kwargs(doc: dict[str, Any]) -> dict[str, Any]:
    """If-Match arguments for *doc*, or nothing when it has no ETag yet."""
    etag = doc.get("_etag")
    if not etag:
        return {}
    try:
        from azure.core import MatchConditions
    except ImportError:  # the fake container in tests keys off `etag` alone
        return {"etag": etag}
    return {"etag": etag, "match_condition": MatchConditions.IfNotModified}


def rmw(
    container: Any,
    *,
    read: Callable[[], Optional[dict[str, Any]]],
    mutate: Callable[[dict[str, Any]], T],
    missing: Callable[[], T] | None = None,
) -> T:
    """Read a document, mutate it, and write it back atomically.

    ``read`` re-runs on every attempt so ``mutate`` always sees current state —
    which is what lets a caller re-check its guards against a concurrent
    writer's changes. ``mutate`` returns the caller's result and may raise to
    abort the cycle. ``missing`` supplies the result when the document is gone;
    without it, a missing document raises.

    Raises:
        RepositoryConflict: the document kept changing for MAX_ATTEMPTS.
    """
    for attempt in range(MAX_ATTEMPTS):
        doc = read()
        if doc is None:
            if missing is not None:
                return missing()
            raise RepositoryConflict("Document disappeared during read-modify-write")

        result = mutate(doc)
        try:
            container.upsert_item(doc, **_write_kwargs(doc))
        except Exception as exc:
            if not _is_precondition_failure(exc):
                raise
            # Someone else wrote first: back off, re-read, and replay.
            time.sleep(_BASE_BACKOFF_SECONDS * (2**attempt) * (0.5 + random.random()))
            continue
        return result

    raise RepositoryConflict(
        f"Gave up after {MAX_ATTEMPTS} attempts; the document is under heavy contention"
    )
