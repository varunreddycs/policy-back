"""Load the NIST CSF 2.0 -> SP 800-53 Rev 5.2.0 / ISO 27001:2022 crosswalk as references.

Prerequisites: the 800-53 catalog (tools/seed_nist_800_53.py) and the CSF 2.0
catalog (tools/seed_nist_csf_2.py) are already seeded for the tenant.

Mappings are UNTYPED: the source says the two items are related, not whether one
is a subset of the other, so relationship_type and strength stay None.

  CSF -> SP 800-53 : cross_policy / resolved   when the control exists in the corpus,
                     cross_policy / unresolved otherwise (never dropped)
  CSF -> ISO 27001 : external_authority / external, id only (ISO text is copyrighted)

Reference ids are deterministic, so reruns upsert instead of duplicating.

Env required (not in --dry-run): COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE

Usage:
  uv run --with azure-cosmos python tools/load_nist_crosswalk.py --dry-run
  uv run --with azure-cosmos python tools/load_nist_crosswalk.py \
      --tenant 00000000-0000-0000-0000-000000000001
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packages.core.control_ids import NIST_800_53_FAMILIES
from tools.nist_seed_common import JsonDoc, det_id
from tools.seed_nist_csf_2 import csf_section_id, csf_version_id

NIST_REVISION = "SP 800-53 Rev 5.2.0"
ISO_REVISION = "ISO/IEC 27001:2022"
SourceIds = Mapping[str, tuple[str, str]]  # csf id -> (section_id, policy_version_id)
Targets = Mapping[str, tuple[str, str]]  # control id -> (section_id, policy_id)


def csf_section_ids(catalog: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    """CSF subcategory id -> (section id, version id), derived exactly as the CSF seeder derives them."""
    categories = {c["id"]: c["function_id"] for c in catalog["categories"]}
    return {
        sub["id"]: (csf_section_id(sub["id"]), csf_version_id(categories[sub["category_id"]]))
        for sub in catalog["subcategories"]
    }


def needed_800_53_ids(catalog: Mapping[str, Any]) -> set[str]:
    return {ref for sub in catalog["subcategories"] for ref in sub["refs_800_53"]}


def build_crosswalk_docs(
    catalog: Mapping[str, Any],
    *,
    tenant_id: str,
    csf_section_ids: SourceIds,
    nist_targets: Targets,
) -> list[JsonDoc]:
    """Pure: one reference doc per (CSF subcategory, target). No I/O, no clocks, no randomness."""
    sha: str = catalog["source_sha256"]
    mapping_source: str = catalog["mapping_source"]
    extractor_version = f"nist-olir-csf2@{sha[:12]}"
    docs: list[JsonDoc] = []

    def base(csf_id: str, *, revision: str, target_id: str, line: str, reference_type: str) -> JsonDoc:
        section_id, version_id = csf_section_ids[csf_id]
        return {
            "id": det_id("csf2-xref", csf_id, revision, target_id),
            "tenant_id": tenant_id,
            "source_section_id": section_id,
            "source_policy_version_id": version_id,
            "reference_type": reference_type,
            "target_external_uri": None,
            "matched_text": line,
            "match_offset": None,
            "extractor_version": extractor_version,
            "confidence": 1.0,
            "relationship_type": None,
            "strength": None,
            "mapping_source": mapping_source,
            "mapping_revision": revision,
        }

    for sub in catalog["subcategories"]:
        csf_id: str = sub["id"]
        for control_id in sub["refs_800_53"]:
            doc = base(
                csf_id,
                revision=NIST_REVISION,
                target_id=control_id,
                line=f"{NIST_REVISION}: {control_id}",
                reference_type="cross_policy",
            )
            doc["target_external_label"] = f"NIST {NIST_REVISION} {control_id}"
            target = nist_targets.get(control_id)
            if target is None:
                doc.update(resolution_status="unresolved", target_section_id=None, target_policy_id=None)
            else:
                doc.update(resolution_status="resolved", target_section_id=target[0], target_policy_id=target[1])
            docs.append(doc)
        for iso_id in sub["refs_iso_27001_2022"]:
            doc = base(
                csf_id,
                revision=ISO_REVISION,
                target_id=iso_id,
                line=f"{ISO_REVISION}: {iso_id}",
                reference_type="external_authority",
            )
            doc.update(
                resolution_status="external",
                target_section_id=None,
                target_policy_id=None,
                target_external_label=f"{ISO_REVISION} {iso_id}",
            )
            docs.append(doc)
    return docs


def nist_800_53_version_policies() -> dict[str, str]:
    """version id -> policy id for the 800-53 family policies, as tools/seed_nist_800_53.py derives them."""
    return {det_id("version", fam): det_id("policy", fam) for fam in sorted(NIST_800_53_FAMILIES)}


def resolve_nist_targets(sections_container: Any, tenant_id: str, control_ids: set[str]) -> dict[str, tuple[str, str]]:
    """Look up 800-53 sections by section_path, keeping only those inside the 800-53 policies."""
    version_policy = nist_800_53_version_policies()
    rows = sections_container.query_items(
        query=(
            "SELECT c.id, c.section_path, c.policy_version_id FROM c "
            "WHERE c.tenant_id = @tenant AND ARRAY_CONTAINS(@paths, c.section_path)"
        ),
        parameters=[
            {"name": "@tenant", "value": tenant_id},
            {"name": "@paths", "value": sorted(control_ids)},
        ],
        partition_key=tenant_id,
    )
    targets: dict[str, tuple[str, str]] = {}
    for row in rows:
        policy_id = version_policy.get(row["policy_version_id"])
        if policy_id is not None:
            targets[row["section_path"]] = (row["id"], policy_id)
    return targets


def summarize(docs: list[JsonDoc]) -> Counter[str]:
    return Counter(str(d["resolution_status"]) for d in docs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/nist/csf2_olir.json")
    ap.add_argument("--tenant", default="00000000-0000-0000-0000-000000000001")
    ap.add_argument("--dry-run", action="store_true", help="build docs and print counts; never connects to Cosmos")
    args = ap.parse_args()

    catalog = json.loads(Path(args.data).read_text(encoding="utf-8"))
    needed = needed_800_53_ids(catalog)

    if args.dry_run:
        print("dry-run: resolving 800-53 targets needs Cosmos, so all CSF->800-53 refs are counted as unresolved")
        targets: dict[str, tuple[str, str]] = {}
        sections_container = None
    else:
        from azure.cosmos import CosmosClient

        client = CosmosClient(os.environ["COSMOS_ENDPOINT"], os.environ["COSMOS_KEY"])
        db = client.get_database_client(os.environ.get("COSMOS_DATABASE", "policydb"))
        sections_container = db.get_container_client("sections")
        targets = resolve_nist_targets(sections_container, args.tenant, needed)
        print(f"resolved {len(targets)}/{len(needed)} distinct 800-53 controls in the corpus")

    docs = build_crosswalk_docs(
        catalog,
        tenant_id=args.tenant,
        csf_section_ids=csf_section_ids(catalog),
        nist_targets=targets,
    )
    counts = summarize(docs)
    print(
        f"built {len(docs)} references: resolved={counts['resolved']} "
        f"unresolved={counts['unresolved']} iso={counts['external']}"
    )
    if args.dry_run or sections_container is None:
        print("dry-run: nothing written")
        return

    from packages.db.repositories.cosmos.cosmos_repos import CosmosReferenceRepository

    repo = CosmosReferenceRepository(
        db.get_container_client("references"),
        db.get_container_client("policies"),
        sections_container,
    )
    written = repo.bulk_insert(docs)
    print(f"upserted {written} references")
    print("DONE")


if __name__ == "__main__":
    main()
