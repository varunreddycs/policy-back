"""Seed Cosmos DB with NIST CSF 2.0 as its own framework.

Reads the catalog produced by tools/nist_csf/convert_olir_xlsx.py
(data/nist/csf2_olir.json) and builds:
  - one policy per CSF Function (GV, ID, PR, DE, RS, RC), one version each
  - one section per Category ("GV.OC") and per Subcategory ("GV.OC-01")
  - one denormalized embedding per section

Subcategory section titles are the parent category's name. CSF statements are
whole sentences ("The organizational mission is understood and informs ..."),
so a "short first clause" would be an arbitrary truncation, whereas the category
name is the official, stable label a reader would cite. The full statement leads
the section text, prefixed with the CSF id so the id is also embedded.

Env required (not in --dry-run):
  COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE
  AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION,
  AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT

Usage:
  uv run --with azure-cosmos python tools/seed_nist_csf_2.py --dry-run
  uv run --with azure-cosmos python tools/seed_nist_csf_2.py \
      --tenant 00000000-0000-0000-0000-000000000001
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from tools import nist_seed_common as common
from tools.nist_seed_common import JsonDoc, det_id

CATEGORY = "NIST CSF 2.0"
AUTHORITY_LEVEL = 5
EFFECTIVE_DATE = "2024-02-26"  # CSF 2.0 publication date
PUBLIC_URL = "https://www.nist.gov/cyberframework"
FUNCTION_ORDER = ("GV", "ID", "PR", "DE", "RS", "RC")
EXAMPLES_HEADING = "Implementation examples:"


def csf_policy_id(function_id: str) -> str:
    return det_id("csf2-policy", function_id)


def csf_version_id(function_id: str) -> str:
    return det_id("csf2-version", function_id)


def csf_section_id(csf_id: str) -> str:
    """Section id for a category ("GV.OC") or subcategory ("GV.OC-01")."""
    return det_id("csf2-section", csf_id)


def csf_embedding_id(csf_id: str) -> str:
    return det_id("csf2-embedding", csf_id)


def _subcategory_text(sub: dict[str, Any]) -> str:
    text = f"{sub['id']}: {sub['text']}"
    examples = sub.get("examples") or []
    if examples:
        bullets = "\n".join(f"- {ex}" for ex in examples)
        text = f"{text}\n\n{EXAMPLES_HEADING}\n{bullets}"
    return text


def build_docs(
    catalog: dict[str, Any], tenant_id: str
) -> tuple[list[JsonDoc], list[JsonDoc], list[JsonDoc]]:
    """Pure doc construction: (policies, sections, embeddings). No I/O."""
    policies: list[JsonDoc] = []
    sections: list[JsonDoc] = []
    embeddings: list[JsonDoc] = []

    functions = {f["id"]: f for f in catalog["functions"]}
    ordered = [fid for fid in FUNCTION_ORDER if fid in functions]
    ordered += sorted(set(functions) - set(ordered))

    for fid in ordered:
        function = functions[fid]
        policy_id = csf_policy_id(fid)
        version_id = csf_version_id(fid)
        function_name = function["name"].title()
        policy_name = f"NIST CSF 2.0 — {function_name} ({fid})"

        version = common.version_doc(
            version_id=version_id,
            version_label="2.0",
            title=function_name,
            effective_date=EFFECTIVE_DATE,
            metadata={"source": "NIST CSF 2.0", "function": fid},
        )
        policies.append(
            common.policy_doc(
                policy_id=policy_id,
                tenant_id=tenant_id,
                external_id=f"nist-csf-2-{fid.lower()}",
                name=policy_name,
                category=CATEGORY,
                authority_level=AUTHORITY_LEVEL,
                version=version,
            )
        )

        index = 0
        for cat in (c for c in catalog["categories"] if c["function_id"] == fid):
            entries: list[tuple[str, str, str]] = [
                (cat["id"], cat["name"], f"{cat['id']} {cat['name']}: {cat['text']}")
            ]
            entries += [
                (sub["id"], cat["name"], _subcategory_text(sub))
                for sub in catalog["subcategories"]
                if sub["category_id"] == cat["id"]
            ]
            for csf_id, title, text in entries:
                section = common.section_doc(
                    section_id=csf_section_id(csf_id),
                    tenant_id=tenant_id,
                    version_id=version_id,
                    index=index,
                    path=csf_id,
                    title=title,
                    text=text,
                )
                sections.append(section)
                embeddings.append(
                    common.embedding_doc(
                        embedding_id=csf_embedding_id(csf_id),
                        section=section,
                        policy_id=policy_id,
                        policy_name=policy_name,
                        authority_level=AUTHORITY_LEVEL,
                        effective_date=EFFECTIVE_DATE,
                        public_url=PUBLIC_URL,
                    )
                )
                index += 1

    return policies, sections, embeddings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/nist/csf2_olir.json")
    ap.add_argument("--tenant", default="00000000-0000-0000-0000-000000000001")
    ap.add_argument("--dry-run", action="store_true", help="build docs and print counts; no embedding, no Cosmos")
    args = ap.parse_args()

    catalog = json.loads(Path(args.data).read_text(encoding="utf-8"))
    policies, sections, embeddings = build_docs(catalog, args.tenant)
    print(f"built {len(policies)} policies, {len(sections)} sections, {len(embeddings)} embeddings")
    if args.dry_run:
        print("dry-run: nothing embedded or written")
        return

    from azure.cosmos import CosmosClient

    from packages.embeddings import embed_texts

    print("embedding section texts...")
    vectors = embed_texts([str(e["text"]) for e in embeddings])
    if len(vectors) != len(embeddings):
        raise RuntimeError(f"embedding count mismatch {len(vectors)} != {len(embeddings)}")
    for e, v in zip(embeddings, vectors):
        e["embedding"] = v
    print(f"embedded {len(vectors)} texts (dim={len(vectors[0])})")

    client = CosmosClient(os.environ["COSMOS_ENDPOINT"], os.environ["COSMOS_KEY"])
    db = client.get_database_client(os.environ.get("COSMOS_DATABASE", "policydb"))
    for container_name, docs in (("policies", policies), ("sections", sections), ("embeddings", embeddings)):
        container = db.get_container_client(container_name)
        for doc in docs:
            container.upsert_item(doc)
        print(f"upserted {len(docs)} into {container_name}")
    print("DONE")


if __name__ == "__main__":
    main()
