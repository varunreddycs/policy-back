"""S2: as-of version pinning verified against a real PostgreSQL.

Creates a policy with two READY versions (effective 2024-01-01 and 2025-06-01)
under a throwaway tenant, then asserts the FTS retriever returns the version
authoritative on each requested date. Cleans up after itself.

    RUN_INTEGRATION=1 DATABASE_URL=postgresql+psycopg://... uv run pytest tests/integration/test_as_of_live.py
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from packages.core.dtos import PolicyScope
from packages.retrieval.pgsql_fts_provider import PgsqlFtsRetriever

pytestmark = pytest.mark.integration


def _should_run() -> bool:
    return os.environ.get("RUN_INTEGRATION") == "1" and bool(
        os.environ.get("DATABASE_URL")
    )


@pytest.fixture(scope="module")
def engine():
    if not _should_run():
        pytest.skip("RUN_INTEGRATION!=1 or DATABASE_URL unset")
    eng = create_engine(os.environ["DATABASE_URL"], future=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable: {exc}")
    return eng


@pytest.fixture()
def corpus(engine):
    """A tenant with one policy and two dated READY versions."""
    tenant_id = uuid.uuid4()
    policy_id = uuid.uuid4()
    v1, v2 = uuid.uuid4(), uuid.uuid4()
    s1, s2 = uuid.uuid4(), uuid.uuid4()

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
            {
                "id": str(tenant_id),
                "slug": f"asof-test-{tenant_id.hex[:8]}",
                "name": f"asof-test-{tenant_id.hex[:8]}",
            },
        )
        conn.execute(
            text(
                "INSERT INTO policies "
                "(id, tenant_id, external_id, name, status, authority_level, department_scope) "
                "VALUES (:id, :tid, :ext, 'As-Of Test Policy', 'active', 50, 'all')"
            ),
            {
                "id": str(policy_id),
                "tid": str(tenant_id),
                "ext": f"asof-{policy_id.hex[:8]}",
            },
        )
        for vid, num, eff, is_current, label in (
            (v1, 1, date(2024, 1, 1), False, "2024-rules"),
            (v2, 2, date(2025, 6, 1), True, "2025-rules"),
        ):
            conn.execute(
                text(
                    "INSERT INTO policy_versions "
                    "(id, tenant_id, policy_id, version_number, version_label, "
                    " effective_date, blob_container, blob_name, content_sha256, "
                    " metadata_json, metadata_sha256, parse_status, is_current, "
                    " parse_status_updated_at, created_at) "
                    "VALUES (:id, :tid, :pid, :num, :label, :eff, 'test', 'test.txt', "
                    " :sha, '{}', :sha, 'ready', :cur, now(), now())"
                ),
                {
                    "id": str(vid),
                    "tid": str(tenant_id),
                    "pid": str(policy_id),
                    "num": num,
                    "label": label,
                    "eff": eff,
                    "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                    "cur": is_current,
                },
            )
        for sid, vid, body in (
            (s1, v1, "Reimbursement requests must be submitted within 30 days."),
            (s2, v2, "Reimbursement requests must be submitted within 60 days."),
        ):
            conn.execute(
                text(
                    "INSERT INTO policy_sections "
                    "(id, tenant_id, policy_version_id, section_index, title, text, content_sha256) "
                    "VALUES (:id, :tid, :vid, 1, 'Reimbursement', :body, :sha)"
                ),
                {
                    "id": str(sid),
                    "tid": str(tenant_id),
                    "vid": str(vid),
                    "body": body,
                    "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                },
            )

    yield {"tenant_id": tenant_id, "v1": v1, "v2": v2}

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM policy_sections WHERE tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )
        conn.execute(
            text("DELETE FROM policy_versions WHERE tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )
        conn.execute(
            text("DELETE FROM policies WHERE tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )
        conn.execute(
            text("DELETE FROM tenants WHERE id = :tid"), {"tid": str(tenant_id)}
        )


def _retrieve(engine, corpus, as_of: date | None):
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        retriever = PgsqlFtsRetriever(session=session)
        return retriever.retrieve(
            tenant_id=corpus["tenant_id"],
            query="reimbursement submitted",
            scope=PolicyScope(as_of=as_of) if as_of else PolicyScope(),
        )


def test_as_of_before_v2_returns_v1(engine, corpus) -> None:
    """On 2024-12-31 only the 2024 rules were in force."""
    results = _retrieve(engine, corpus, date(2024, 12, 31))

    versions = {c.policy_version_id for c in results}
    assert versions == {corpus["v1"]}
    assert "30 days" in results[0].text
    assert results[0].metadata["version_label"] == "2024-rules"
    assert results[0].metadata["is_current"] is True, "authoritative AS OF that date"


def test_as_of_after_v2_returns_v2(engine, corpus) -> None:
    results = _retrieve(engine, corpus, date(2025, 12, 31))

    versions = {c.policy_version_id for c in results}
    assert versions == {corpus["v2"]}
    assert "60 days" in results[0].text


def test_as_of_before_any_version_returns_nothing(engine, corpus) -> None:
    """Before the first effective date there was no requirement at all."""
    results = _retrieve(engine, corpus, date(2023, 1, 1))

    assert results == []


def test_without_as_of_only_the_current_version_returns(engine, corpus) -> None:
    results = _retrieve(engine, corpus, None)

    versions = {c.policy_version_id for c in results}
    assert versions == {corpus["v2"]}
