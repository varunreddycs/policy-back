from __future__ import annotations

import uuid
from typing import Any

from packages.core.dtos import (
    AnswerResponse,
    AskRequest,
    CitationItem,
    EvidenceCandidate,
    PolicyScope,
    UserContext,
)
from packages.db.repositories.base import IReferenceRepository
from packages.db.repositories.cosmos.cosmos_repos import CosmosReferenceRepository
from packages.db.repositories.repo_dtos import PolicyReferenceDTO
from packages.rag.ask_service import AskService
from packages.rag.related_controls import MAX_RELATED_CONTROLS, derive_related_controls
from packages.retrieval.base import IVectorRetriever

OLIR = "NIST OLIR CSF 2.0 informative references"
NIST_REV = "SP 800-53 Rev 5.2.0"
ISO_REV = "ISO/IEC 27001:2022"


def _ref(**over: Any) -> PolicyReferenceDTO:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "reference_type": "cross_policy",
        "resolution_status": "resolved",
        "matched_text": "x",
        "confidence": 1.0,
        "extractor_version": "v",
        "source_section_id": uuid.uuid4(),
        "source_policy_version_id": uuid.uuid4(),
        "mapping_source": OLIR,
        "mapping_revision": NIST_REV,
    }
    base.update(over)
    return PolicyReferenceDTO(**base)


def _csf_to_800_53(csf: uuid.UUID, ac: uuid.UUID, **over: Any) -> PolicyReferenceDTO:
    return _ref(
        source_section_id=csf,
        source_section_path="PR.AA-01",
        source_policy_name="NIST CSF 2.0 - Protect (PR)",
        target_section_id=ac,
        target_section_path="AC-2",
        target_policy_name="800-53 AC",
        **over,
    )


# --- pure derivation -------------------------------------------------------------


def test_resolved_mapping_seen_from_the_800_53_end_yields_the_csf_control() -> None:
    csf, ac = uuid.uuid4(), uuid.uuid4()

    [rc], truncated = derive_related_controls([_csf_to_800_53(csf, ac)], ac)

    assert (rc.label, rc.framework, rc.control_id) == ("CSF 2.0 PR.AA-01", "NIST CSF 2.0", "PR.AA-01")
    assert rc.section_id == csf
    assert rc.relationship == "related"
    assert rc.mapping_source == OLIR
    assert truncated is False


def test_resolved_mapping_seen_from_the_csf_end_yields_the_800_53_control() -> None:
    csf, ac = uuid.uuid4(), uuid.uuid4()

    [rc], _ = derive_related_controls([_csf_to_800_53(csf, ac, relationship_type="subset_of")], csf)

    assert (rc.label, rc.framework, rc.control_id) == ("SP 800-53 Rev 5.2.0 AC-2", "NIST SP 800-53 Rev 5.2.0", "AC-2")
    assert rc.section_id == ac
    assert rc.relationship == "subset_of"


def test_unresolved_target_uses_the_external_label() -> None:
    csf = uuid.uuid4()
    ref = _ref(
        source_section_id=csf,
        resolution_status="unresolved",
        target_external_label=f"NIST {NIST_REV} AC-2(3)",
    )

    [rc], _ = derive_related_controls([ref], csf)

    assert (rc.label, rc.control_id, rc.section_id) == ("SP 800-53 Rev 5.2.0 AC-2(3)", "AC-2(3)", None)


def test_iso_external_mapping_from_csf() -> None:
    csf = uuid.uuid4()
    ref = _ref(
        source_section_id=csf,
        reference_type="external_authority",
        resolution_status="external",
        mapping_revision=ISO_REV,
        target_external_label=f"{ISO_REV} A.5.16",
    )

    [rc], _ = derive_related_controls([ref], csf)

    assert (rc.label, rc.framework, rc.control_id) == ("ISO/IEC 27001:2022 A.5.16", ISO_REV, "A.5.16")


def test_duplicates_are_collapsed_and_output_is_naturally_sorted() -> None:
    csf = uuid.uuid4()
    refs = [
        _ref(source_section_id=csf, target_external_label=f"NIST {NIST_REV} {cid}")
        for cid in ("AC-10", "AC-2", "AC-2", "AC-1")
    ]

    controls, _ = derive_related_controls(refs, csf)

    assert [c.control_id for c in controls] == ["AC-1", "AC-2", "AC-10"]


def test_rows_without_mapping_source_are_ignored() -> None:
    csf, ac = uuid.uuid4(), uuid.uuid4()
    text_ref = _csf_to_800_53(csf, ac, mapping_source=None, mapping_revision=None)

    assert derive_related_controls([text_ref], ac) == ([], False)


def test_mappings_are_never_chained_transitively() -> None:
    csf, ac = uuid.uuid4(), uuid.uuid4()
    refs = [
        _csf_to_800_53(csf, ac),
        _ref(
            source_section_id=csf,
            reference_type="external_authority",
            resolution_status="external",
            mapping_revision=ISO_REV,
            target_external_label=f"{ISO_REV} A.5.16",
        ),
    ]

    controls, _ = derive_related_controls(refs, ac)

    assert [c.framework for c in controls] == ["NIST CSF 2.0"]


def test_unknown_source_framework_is_not_guessed() -> None:
    ac = uuid.uuid4()
    ref = _ref(target_section_id=ac, source_section_path="X-1", source_policy_name="Some Other Catalog")

    [rc], _ = derive_related_controls([ref], ac)

    assert rc.framework == "unknown"


def test_cap_and_truncation_flag() -> None:
    csf = uuid.uuid4()
    refs = [_ref(source_section_id=csf, target_external_label=f"NIST {NIST_REV} AC-{i}") for i in range(20)]

    controls, truncated = derive_related_controls(refs, csf)

    assert len(controls) == MAX_RELATED_CONTROLS
    assert truncated is True


# --- Cosmos repository -------------------------------------------------------------


class _Container:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.query_count = 0

    def query_items(
        self, *, query: str, parameters: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.query_count += 1
        params = {p["name"]: p["value"] for p in (parameters or [])}
        if "IS_DEFINED(c.mapping_source)" in query:
            ids = params["@ids"]
            return [
                r
                for r in self.rows
                if r.get("mapping_source") is not None
                and (r["source_section_id"] in ids or r.get("target_section_id") in ids)
            ]
        if "ARRAY_CONTAINS(@ids, c.id)" in query:
            return [r for r in self.rows if r["id"] in params["@ids"]]
        return [
            {**r, "version_ids": [v["id"] for v in r.get("versions", [])]}
            for r in self.rows
            if r["id"] in params["@pids"] or any(v["id"] in params["@vids"] for v in r.get("versions", []))
        ]


def _cosmos_fixture() -> tuple[CosmosReferenceRepository, uuid.UUID, uuid.UUID, uuid.UUID, dict[str, _Container]]:
    tenant, csf_sec, ac_sec = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    csf_ver, ac_ver, csf_pol, ac_pol = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def doc(**over: Any) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "tenant_id": str(tenant),
            "reference_type": "cross_policy",
            "resolution_status": "resolved",
            "matched_text": "x",
            "source_section_id": str(csf_sec),
            "source_policy_version_id": str(csf_ver),
            "target_section_id": str(ac_sec),
            "target_policy_id": str(ac_pol),
            "mapping_source": OLIR,
            "mapping_revision": NIST_REV,
        }
        d.update(over)
        return d

    refs = _Container([doc(), doc(mapping_source=None, mapping_revision=None), doc(source_section_id=str(uuid.uuid4()))])
    # Real shapes: section docs have no policy_id; policy docs embed versions.
    sections = _Container(
        [
            {"id": str(csf_sec), "title": "Identities", "section_path": "PR.AA-01", "policy_version_id": str(csf_ver)},
            {"id": str(ac_sec), "title": "Account Management", "section_path": "AC-2", "policy_version_id": str(ac_ver)},
        ]
    )
    policies = _Container(
        [
            {"id": str(csf_pol), "name": "NIST CSF 2.0 - Protect (PR)", "versions": [{"id": str(csf_ver)}]},
            {"id": str(ac_pol), "name": "800-53 AC", "versions": [{"id": str(ac_ver)}]},
        ]
    )
    repo = CosmosReferenceRepository(refs, policies, sections)
    return repo, tenant, csf_sec, ac_sec, {"refs": refs, "sections": sections, "policies": policies}


def test_cosmos_mappings_are_one_query_per_container_and_exclude_text_refs() -> None:
    repo, tenant, csf_sec, ac_sec, c = _cosmos_fixture()

    dtos = repo.list_mappings_for_sections(tenant_id=tenant, section_ids=[ac_sec])

    assert len(dtos) == 2  # the mapping_source-NULL row is excluded; the unrelated-source row shares ac_sec
    assert (c["refs"].query_count, c["sections"].query_count, c["policies"].query_count) == (1, 1, 1)
    assert all(d.mapping_source == OLIR for d in dtos)
    hydrated = next(d for d in dtos if d.source_section_id == csf_sec)
    assert hydrated.source_policy_name == "NIST CSF 2.0 - Protect (PR)"
    assert hydrated.target_policy_name == "800-53 AC"
    assert hydrated.source_section_path == "PR.AA-01"
    [rc], _ = derive_related_controls([hydrated], ac_sec)
    assert rc.label == "CSF 2.0 PR.AA-01"


def test_cosmos_mappings_empty_ids_issue_no_queries() -> None:
    repo, tenant, _, _, c = _cosmos_fixture()

    assert repo.list_mappings_for_sections(tenant_id=tenant, section_ids=[]) == []
    assert (c["refs"].query_count, c["sections"].query_count, c["policies"].query_count) == (0, 0, 0)


# --- AskService enrichment ---------------------------------------------------------


class _Retriever(IVectorRetriever):
    def __init__(self, items: list[EvidenceCandidate]) -> None:
        self._items = items

    def retrieve(
        self,
        *,
        tenant_id: uuid.UUID,
        query: str,
        scope: PolicyScope | None = None,
        user: UserContext | None = None,
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        return self._items


class _Audit:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def write(
        self, *, tenant_id: uuid.UUID, event_type: str, correlation_id: str | None, payload: dict[str, Any]
    ) -> uuid.UUID:
        self.payloads.append(payload)
        return uuid.uuid4()


class _Refs(IReferenceRepository):
    def __init__(self, rows: list[PolicyReferenceDTO] | None = None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.calls: list[list[uuid.UUID]] = []

    def list_mappings_for_sections(
        self, *, tenant_id: uuid.UUID, section_ids: list[uuid.UUID]
    ) -> list[PolicyReferenceDTO]:
        self.calls.append(section_ids)
        if self.error is not None:
            raise self.error
        return self.rows


    def bulk_insert(self, refs: list[dict[str, Any]]) -> int:
        raise NotImplementedError

    def delete_for_section(self, *, section_id: uuid.UUID) -> int:
        raise NotImplementedError

    def delete_for_policy_version(self, *, policy_version_id: uuid.UUID) -> int:
        raise NotImplementedError

    def list_outbound_for_section(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> list[PolicyReferenceDTO]:
        raise NotImplementedError

    def list_inbound_for_section(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> list[PolicyReferenceDTO]:
        raise NotImplementedError

    def list_for_policy_version(
        self, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[PolicyReferenceDTO]:
        raise NotImplementedError

    def section_exists_for_tenant(self, *, tenant_id: uuid.UUID, section_id: uuid.UUID) -> bool:
        raise NotImplementedError

    def policy_version_exists_for_tenant(self, *, tenant_id: uuid.UUID, policy_version_id: uuid.UUID) -> bool:
        raise NotImplementedError


def _ask(refs: IReferenceRepository | None, sections: list[uuid.UUID]) -> tuple[AnswerResponse, _Audit]:
    tenant = uuid.uuid4()
    cands = [
        EvidenceCandidate(
            policy_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            section_id=s,
            text="Accounts must be reviewed quarterly.",
            score=0.9,
            source="hybrid",
            metadata={"title": "Account Management", "section_path": "AC-2", "policy_name": "800-53 AC"},
        )
        for s in sections
    ]
    audit = _Audit()
    service = AskService(retriever=_Retriever(cands), audit_repo=audit, references_repo=refs)  # type: ignore[arg-type]
    request = AskRequest(tenant_id=tenant, question="How often are accounts reviewed?")
    return service.ask(request), audit


def test_ask_attaches_related_controls_to_citations_with_one_lookup() -> None:
    csf, ac = uuid.uuid4(), uuid.uuid4()
    refs = _Refs([_csf_to_800_53(csf, ac)])

    response, audit = _ask(refs, [ac])

    assert len(refs.calls) == 1
    [citation] = response.citation_items
    assert [c.label for c in citation.related_controls] == ["CSF 2.0 PR.AA-01"]
    persisted = audit.payloads[0]["response"]["citation_items"][0]["related_controls"]
    assert persisted[0]["control_id"] == "PR.AA-01"


def test_ask_still_answers_when_the_lookup_raises() -> None:
    refs = _Refs(error=RuntimeError("cosmos down"))

    response, _ = _ask(refs, [uuid.uuid4()])

    assert response.citation_items
    assert all(c.related_controls == [] for c in response.citation_items)
    assert len(refs.calls) == 1


def test_ask_without_references_repo_is_unchanged() -> None:
    response, _ = _ask(None, [uuid.uuid4()])

    assert response.citation_items
    assert all(isinstance(c, CitationItem) and c.related_controls == [] for c in response.citation_items)
