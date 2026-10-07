"""NIST CSF 2.0 converter, seeder doc-building and crosswalk reference docs."""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from pathlib import Path

import pytest

import tools.nist_seed_common as common
from packages.core.control_ids import primary_control_id
from packages.db.repositories.cosmos.cosmos_repos import CosmosReferenceRepository
from tools import seed_nist_800_53, seed_nist_csf_2
from tools.load_nist_crosswalk import (
    build_crosswalk_docs,
    csf_section_ids,
    needed_800_53_ids,
    nist_800_53_version_policies,
    resolve_nist_targets,
)
from tools.nist_csf.convert_olir_xlsx import (
    CsfCatalog,
    canonical_nist_id,
    parse_csf_rows,
    parse_iso_ids,
)

DATA = Path(__file__).resolve().parents[2] / "data" / "nist" / "csf2_olir.json"
TENANT = "00000000-0000-0000-0000-000000000001"

ROWS: list[tuple[object, ...]] = [
    (None, "title row", None, None, None),
    ("Function", "Category", "Subcategory", "Implementation Examples", "Informative References"),
    ("GOVERN (GV): Strategy is set", None, None, None, "ISO/IEC 27001:2022: Mandatory Clause: 6.1"),
    (None, "Organizational Context (GV.OC): Circumstances are understood", None, None, None),
    (
        None,
        None,
        "GV.OC-01: The mission is understood",
        "Ex1: Share the mission\nEx2: Review it yearly",
        "\n".join(
            [
                "CSF v1.1: ID.BE-2",
                "ISO/IEC 27001:2022: Mandatory Clause:  4.1",
                "ISO/IEC 27001:2022: Mandatory Clause: 4.2 (a)",
                "ISO/IEC 27001:2022: Control  8.6",
                "ISO/IEC 27001:2022: Annex A Controls: 5.24",
                "ISO/IEC 27001:2022: Annex A Controls:",
                "ISO/IEC 27001:2022: Mandatory Clause: None",
                "ISO/IEC 27001:2022: Mandatory Clause: 7.1, 7.2",
                "PCI DSS: 12.1.1",
                "SP 800-53 Rev 5.1.1: PM-11",
                "SP 800-53 Rev 5.1.1: SR-03",
                "SP 800-53 Rev 5.2.0: PM-11",
                "SP 800-53 Rev 5.2.0: CM-07(02)",
                "SP 800-53 Rev 5.2.0: AC-2",
                "SP 800-53 Rev 5.2.0: PT",
            ]
        ),
    ),
    (None, None, "GV.OC-02: No references here", "Ex1: Only example", None),
    (None, None, "ID.BE-01: [Withdrawn: Incorporated into GV.OC-01]", None, "SP 800-53 Rev 5.2.0: PM-01"),
    (None, "Business Environment (ID.BE): [Withdrawn: Incorporated into GV.OC]", None, None, None),
    ("GOVERN (GV)", None, None, None, None),
]


@pytest.fixture(scope="module")
def parsed() -> CsfCatalog:
    return parse_csf_rows(ROWS)


@pytest.fixture(scope="module")
def real() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


# --- converter ----------------------------------------------------------------


def test_parse_structure(parsed: CsfCatalog) -> None:
    assert [(f.id, f.name, f.text) for f in parsed.functions] == [("GV", "GOVERN", "Strategy is set")]
    assert [(c.id, c.function_id, c.name) for c in parsed.categories] == [
        ("GV.OC", "GV", "Organizational Context")
    ]
    assert [(s.id, s.category_id) for s in parsed.subcategories] == [
        ("GV.OC-01", "GV.OC"),
        ("GV.OC-02", "GV.OC"),
    ]
    assert parsed.subcategories[0].text == "The mission is understood"


def test_withdrawn_rows_are_skipped(parsed: CsfCatalog) -> None:
    assert all("ID.BE" not in s.id for s in parsed.subcategories)
    assert all(c.id != "ID.BE" for c in parsed.categories)


def test_examples_are_split_and_unprefixed(parsed: CsfCatalog) -> None:
    assert parsed.subcategories[0].examples == ["Share the mission", "Review it yearly"]
    assert parsed.subcategories[1].examples == ["Only example"]


def test_only_rev_520_nist_lines_count_and_ids_are_canonical(parsed: CsfCatalog) -> None:
    # 5.1.1-only SR-03 is ignored; zero-padded enhancement "(02)" is canonicalised;
    # the family-only "PT" is not a control id.
    assert parsed.subcategories[0].refs_800_53 == ["AC-2", "CM-7(2)", "PM-11"]


def test_iso_ids_only_and_other_frameworks_ignored(parsed: CsfCatalog) -> None:
    assert parsed.subcategories[0].refs_iso_27001_2022 == ["Clause 4.1", "Clause 4.2(a)", "Clause 7.1", "Clause 7.2", "A.5.24", "A.8.6"]
    assert parsed.subcategories[1].refs_iso_27001_2022 == []


def test_function_level_refs_are_not_attributed_to_subcategories(parsed: CsfCatalog) -> None:
    assert "Clause 6.1" not in parsed.subcategories[0].refs_iso_27001_2022


def test_canonical_nist_id_and_iso_helpers() -> None:
    assert canonical_nist_id("CM-07(02)") == "CM-7(2)"
    assert canonical_nist_id("ac-02") == "AC-2"
    assert canonical_nist_id("PT") is None
    assert parse_iso_ids("ISO/IEC 27001:2022: Control 5.8") == ["A.5.8"]
    assert parse_iso_ids("ISO/IEC 27001:2022: Control  8.6") == ["A.8.6"]
    assert parse_iso_ids("ISO/IEC 27001:2022: Mandatory Clause: 4.2 (a)") == ["Clause 4.2(a)"]
    assert parse_iso_ids("ISO/IEC 27001:2022: Annex A Controls: 5.1, 5.2") == ["A.5.1", "A.5.2"]
    assert parse_iso_ids("ISO/IEC 27001:2022: Mandatory Clause: None") == []
    assert parse_iso_ids("ISO/IEC 27001:2022: Annex A Controls: None") == []


def test_clause_and_annex_with_the_same_number_stay_distinct() -> None:
    clause = parse_iso_ids("ISO/IEC 27001:2022: Mandatory Clause: 6.1")
    annex = parse_iso_ids("ISO/IEC 27001:2022: Annex A Controls: 6.1")
    assert clause == ["Clause 6.1"]
    assert annex == ["A.6.1"]
    assert clause != annex


def test_unknown_category_is_an_error() -> None:
    rows = [(None, None, "GV.ZZ-01: orphan", None, "SP 800-53 Rev 5.2.0: AC-2")]
    with pytest.raises(ValueError, match="unknown categories"):
        parse_csf_rows(rows)


# --- committed data file ------------------------------------------------------


def test_committed_data_counts(real: dict) -> None:
    subs = real["subcategories"]
    n53 = sum(len(s["refs_800_53"]) for s in subs)
    niso = sum(len(s["refs_iso_27001_2022"]) for s in subs)
    with_refs = sum(1 for s in subs if s["refs_800_53"] or s["refs_iso_27001_2022"])
    clauses = sum(i.startswith("Clause ") for s in subs for i in s["refs_iso_27001_2022"])
    annex = sum(i.startswith("A.") for s in subs for i in s["refs_iso_27001_2022"])
    assert (n53, niso, with_refs) == (737, 390, 106)
    assert (clauses, annex) == (89, 301)
    assert (len(real["functions"]), len(real["categories"]), len(subs)) == (6, 22, 106)


def test_committed_data_is_clean(real: dict) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", real["source_sha256"])
    for s in real["subcategories"]:
        for ref in s["refs_800_53"]:
            assert re.fullmatch(r"[A-Z]{2}-[1-9]\d*(\([1-9]\d*\))?", ref), ref
        for iso in s["refs_iso_27001_2022"]:
            assert re.fullmatch(r"(Clause \d+(\.\d+)*(\([a-z]\))?|A\.\d+\.\d+)", iso), iso


# --- CSF seeder ---------------------------------------------------------------


def test_csf_seeder_shapes_and_ids(real: dict) -> None:
    policies, sections, embeddings = seed_nist_csf_2.build_docs(real, TENANT)

    assert [p["external_id"] for p in policies] == [
        f"nist-csf-2-{f}" for f in ("gv", "id", "pr", "de", "rs", "rc")
    ]
    assert len(sections) == len(embeddings) == 22 + 106
    paths = [s["section_path"] for s in sections]
    assert "GV.OC" in paths and "GV.OC-01" in paths and len(set(paths)) == len(paths)
    assert all(p["policy_type"] == "security_control_catalog" and p["category"] == "NIST CSF 2.0" for p in policies)
    assert all(p["versions"][0]["metadata_json"]["source"] == "NIST CSF 2.0" for p in policies)

    ids = [d["id"] for d in (*policies, *sections, *embeddings)]
    assert len(set(ids)) == len(ids)
    version_ids = {p["current_version_id"] for p in policies}
    assert {s["policy_version_id"] for s in sections} == version_ids


def test_csf_ids_never_collide_with_800_53_ids(real: dict) -> None:
    csf_policy_ids = {seed_nist_csf_2.csf_policy_id(f["id"]) for f in real["functions"]}
    nist_policy_ids = {common.det_id("policy", fam) for fam in ("AC", "IR", "SC", "RA", "PM", "PT", "CP")}
    assert not csf_policy_ids & nist_policy_ids
    assert seed_nist_csf_2.csf_section_id("GV.OC") != common.det_id("section", "GV", "oc")


def test_csf_section_paths_are_not_mislabelled_as_800_53_controls(real: dict) -> None:
    _, sections, _ = seed_nist_csf_2.build_docs(real, TENANT)
    assert all(primary_control_id(str(s["section_path"])) is None for s in sections)


def test_csf_seeder_is_deterministic_apart_from_timestamps(
    real: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(common, "now_iso", lambda: "T")
    assert seed_nist_csf_2.build_docs(real, TENANT) == seed_nist_csf_2.build_docs(real, TENANT)


def test_subcategory_text_has_statement_and_examples(real: dict) -> None:
    _, sections, _ = seed_nist_csf_2.build_docs(real, TENANT)
    sec = next(s for s in sections if s["section_path"] == "GV.OC-01")
    text = str(sec["text"])
    assert text.startswith("GV.OC-01: The organizational mission")
    assert "\n\nImplementation examples:\n- " in text
    assert sec["title"] == "Organizational Context"


def test_800_53_seeder_ids_unchanged_by_refactor() -> None:
    # Pinned from the pre-refactor implementation: re-keying would orphan seeded data.
    assert seed_nist_800_53._det_id("policy", "AC") == "0977d809-0c42-57d9-92db-4dbfa66f9bce"
    assert common.det_id("policy", "AC") == seed_nist_800_53._det_id("policy", "AC")
    assert seed_nist_800_53._NS == common.NS


# --- crosswalk docs -----------------------------------------------------------


def _build(real: dict, targets: dict[str, tuple[str, str]]) -> list[dict]:
    return build_crosswalk_docs(
        real, tenant_id=TENANT, csf_section_ids=csf_section_ids(real), nist_targets=targets
    )


def test_crosswalk_resolved_unresolved_and_iso_shapes(real: dict) -> None:
    sec, pol = str(uuid.uuid4()), str(uuid.uuid4())
    docs = _build(real, {"PM-11": (sec, pol)})
    by_status = Counter(d["resolution_status"] for d in docs)
    source = seed_nist_csf_2.csf_section_id("GV.OC-01")
    pm11 = next(
        d
        for d in docs
        if d["target_external_label"] == "NIST SP 800-53 Rev 5.2.0 PM-11" and d["source_section_id"] == source
    )

    assert 0 < by_status["resolved"] < 737
    assert by_status["resolved"] + by_status["unresolved"] == 737
    assert by_status["external"] == 390
    assert pm11["resolution_status"] == "resolved"
    assert pm11["reference_type"] == "cross_policy"
    assert (pm11["target_section_id"], pm11["target_policy_id"]) == (sec, pol)
    assert pm11["matched_text"] == "SP 800-53 Rev 5.2.0: PM-11"
    assert pm11["source_policy_version_id"] == seed_nist_csf_2.csf_version_id("GV")

    unresolved = next(d for d in docs if d["resolution_status"] == "unresolved")
    assert unresolved["target_section_id"] is None and unresolved["target_policy_id"] is None
    assert unresolved["reference_type"] == "cross_policy"
    assert unresolved["target_external_label"].startswith("NIST SP 800-53 Rev 5.2.0 ")

    iso = next(d for d in docs if d["resolution_status"] == "external")
    assert iso["reference_type"] == "external_authority"
    assert iso["target_external_uri"] is None
    assert re.fullmatch(r"ISO/IEC 27001:2022 (Clause \d[\d.()a-z]*|A\.\d+\.\d+)", iso["target_external_label"])
    assert iso["mapping_revision"] == "ISO/IEC 27001:2022"


def test_crosswalk_ids_distinguish_clause_from_annex_with_same_number() -> None:
    catalog = {
        "source_sha256": "0" * 64,
        "mapping_source": "src",
        "subcategories": [
            {"id": "GV.OC-01", "category_id": "GV.OC", "refs_800_53": [], "refs_iso_27001_2022": ["Clause 6.1", "A.6.1"]}
        ],
        "categories": [{"id": "GV.OC", "function_id": "GV"}],
    }
    docs = build_crosswalk_docs(
        catalog, tenant_id=TENANT, csf_section_ids=csf_section_ids(catalog), nist_targets={}
    )
    assert len({d["id"] for d in docs}) == 2
    assert {d["target_external_label"] for d in docs} == {
        "ISO/IEC 27001:2022 Clause 6.1",
        "ISO/IEC 27001:2022 A.6.1",
    }


def test_crosswalk_common_fields_are_untyped(real: dict) -> None:
    docs = _build(real, {})
    assert len(docs) == 737 + 390
    sha = real["source_sha256"]
    for d in docs:
        assert d["relationship_type"] is None and d["strength"] is None
        assert d["match_offset"] is None and d["confidence"] == 1.0
        assert d["extractor_version"] == f"nist-olir-csf2@{sha[:12]}"
        assert d["mapping_source"] == real["mapping_source"]
        assert d["mapping_revision"] in {"SP 800-53 Rev 5.2.0", "ISO/IEC 27001:2022"}


def test_crosswalk_ids_are_deterministic_and_unique(real: dict) -> None:
    targets = {"AC-2": (str(uuid.uuid4()), str(uuid.uuid4()))}
    first, second = _build(real, targets), _build(real, targets)
    assert first == second
    ids = [d["id"] for d in first]
    assert len(set(ids)) == len(ids)


def test_crosswalk_doc_id_does_not_depend_on_resolution(real: dict) -> None:
    unresolved = {d["id"] for d in _build(real, {})}
    resolved = {d["id"] for d in _build(real, {"PM-11": ("s", "p")})}
    assert unresolved == resolved  # resolving later upserts the same docs


def test_crosswalk_docs_are_readable_by_the_cosmos_dto_mapper(real: dict) -> None:
    repo = CosmosReferenceRepository(None, None)
    for doc in _build(real, {"PM-11": (str(uuid.uuid4()), str(uuid.uuid4()))})[:50]:
        dto = repo._to_ref_dto({**doc, "created_at": "2026-01-01T00:00:00+00:00"})
        assert dto.mapping_source == doc["mapping_source"]
        assert dto.mapping_revision == doc["mapping_revision"]
        assert dto.relationship_type is None and dto.strength is None


# --- 800-53 target resolution -------------------------------------------------


class _FakeSections:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.kwargs: dict[str, object] = {}

    def query_items(self, **kwargs: object) -> list[dict[str, str]]:
        self.kwargs = kwargs
        return self.rows


def test_resolve_targets_restricts_to_800_53_policies() -> None:
    version_ac = common.det_id("version", "AC")
    rows = [
        {"id": "sec-ac2", "section_path": "AC-2", "policy_version_id": version_ac},
        {"id": "sec-other", "section_path": "AC-3", "policy_version_id": str(uuid.uuid4())},
    ]
    fake = _FakeSections(rows)

    targets = resolve_nist_targets(fake, TENANT, {"AC-2", "AC-3"})

    assert targets == {"AC-2": ("sec-ac2", common.det_id("policy", "AC"))}
    assert fake.kwargs["partition_key"] == TENANT
    assert nist_800_53_version_policies()[version_ac] == common.det_id("policy", "AC")


def test_needed_ids_cover_every_reference(real: dict) -> None:
    needed = needed_800_53_ids(real)
    assert len(needed) > 100
    assert all(r in needed for s in real["subcategories"] for r in s["refs_800_53"])
