from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from packages.db.policy_query_service import PolicyQueryService


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self._row = row

    def execute(self, stmt):
        return _FakeResult(self._row)


def test_get_policy_section_detail_returns_expected_shape() -> None:
    section_id = uuid4()
    tenant_id = uuid4()
    policy_id = uuid4()
    version_id = uuid4()

    section = SimpleNamespace(
        id=section_id,
        tenant_id=tenant_id,
        section_index=2,
        section_path="Appeals/Timeline",
        title="Timeline",
        text="Appeals must be filed within 30 days.",
    )
    version = SimpleNamespace(
        id=version_id,
        effective_date=date(2026, 3, 1),
        is_current=True,
        metadata_json={"source_url": "https://example.org/source"},
    )
    policy = SimpleNamespace(id=policy_id, name="Appeals Policy")

    service = PolicyQueryService(session=_FakeSession((section, version, policy)))
    detail = service.get_policy_section_detail(tenant_id=tenant_id, section_id=section_id)

    assert detail is not None
    assert detail["section_id"] == section_id
    assert detail["policy_name"] == "Appeals Policy"
    assert detail["public_url"] == "https://example.org/source"


def test_get_policy_section_detail_returns_none_when_missing() -> None:
    service = PolicyQueryService(session=_FakeSession(None))
    assert service.get_policy_section_detail(tenant_id=uuid4(), section_id=uuid4()) is None
