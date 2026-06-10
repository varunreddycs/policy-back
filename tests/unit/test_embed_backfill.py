from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from apps.worker.jobs import embed_backfill


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _sample_rows():
    return [
        SimpleNamespace(
            policy_section_id=uuid4(),
            policy_version_id=uuid4(),
            content_sha256="abc",
            section_text="Users may submit a request within 90 days.",
            section_title="Submission Window",
            effective_date=None,
            authority_level=80,
            department_scope="all",
            policy_type="general",
        ),
        SimpleNamespace(
            policy_section_id=uuid4(),
            policy_version_id=uuid4(),
            content_sha256="def",
            section_text="Fast-track path is available for urgent requests.",
            section_title="Fast Track",
            effective_date=None,
            authority_level=60,
            department_scope="operations",
            policy_type="general",
        ),
    ]


def test_backfill_creates_embeddings(monkeypatch) -> None:
    tenant_id = uuid4()
    session = _FakeSession()
    rows = _sample_rows()

    state = {"fetch_calls": 0, "inserted": 0}

    def fake_fetch_sections_batch(**kwargs):
        state["fetch_calls"] += 1
        return rows if state["fetch_calls"] == 1 else []

    def fake_insert_embeddings_batch(**kwargs):
        state["inserted"] += len(kwargs["rows"])
        return len(kwargs["rows"])

    monkeypatch.setattr(embed_backfill, "_fetch_sections_batch", fake_fetch_sections_batch)
    monkeypatch.setattr(embed_backfill, "_insert_embeddings_batch", fake_insert_embeddings_batch)

    stats = embed_backfill.backfill_embeddings(
        session=session,
        tenant_id=tenant_id,
        only_current=True,
        batch_size=16,
        embedder=lambda texts: [[0.1, 0.2, 0.3] for _ in texts],
    )

    assert stats.scanned == 2
    assert stats.inserted == 2
    assert state["inserted"] == 2


def test_backfill_rerun_creates_zero_duplicates(monkeypatch) -> None:
    tenant_id = uuid4()
    session = _FakeSession()
    rows = _sample_rows()

    inserted_keys = set()

    def make_fetch_once():
        state = {"calls": 0}

        def _fetch(**kwargs):
            state["calls"] += 1
            return rows if state["calls"] == 1 else []

        return _fetch

    def fake_insert_embeddings_batch(**kwargs):
        inserted = 0
        for row in kwargs["rows"]:
            key = (row.policy_section_id, kwargs["embedding_model"])
            if key not in inserted_keys:
                inserted_keys.add(key)
                inserted += 1
        return inserted

    monkeypatch.setattr(embed_backfill, "_fetch_sections_batch", make_fetch_once())
    monkeypatch.setattr(embed_backfill, "_insert_embeddings_batch", fake_insert_embeddings_batch)

    first = embed_backfill.backfill_embeddings(
        session=session,
        tenant_id=tenant_id,
        only_current=True,
        batch_size=2,
        embedder=lambda texts: [[0.4, 0.5] for _ in texts],
    )

    monkeypatch.setattr(embed_backfill, "_fetch_sections_batch", make_fetch_once())
    second = embed_backfill.backfill_embeddings(
        session=session,
        tenant_id=tenant_id,
        only_current=True,
        batch_size=2,
        embedder=lambda texts: [[0.4, 0.5] for _ in texts],
    )

    assert first.inserted == 2
    assert second.inserted == 0
