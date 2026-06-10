"""Seed Cosmos DB with the NIST SP 800-53 Rev 5 control catalog.

Parses the official OSCAL catalog (public domain) into:
  - one policy per control family (AC, IR, IA, ...)
  - one section per control + enhancement (AC-2, AC-2(1), ...)
  - one denormalized embedding per section (text + metadata on the doc)

Embeddings are generated via Azure OpenAI (text-embedding-3-large, 3072-dim)
and written to the `embeddings` container, which must have a cosine DiskANN
vector index on `/embedding`.

Env required:
  COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE
  AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION,
  AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT

Usage:
  uv run --with azure-cosmos python tools/seed_nist_800_53.py \
      --catalog ~/nist_catalog.json --tenant 00000000-0000-0000-0000-000000000001
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from azure.cosmos import CosmosClient

from packages.embeddings import embed_texts

CATALOG_URL = (
    "https://raw.githubusercontent.com/usnistgov/oscal-content/main/"
    "nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json"
)
EFFECTIVE_DATE = "2023-10-12"  # SP 800-53 Rev 5.1.1
CATEGORY = "NIST SP 800-53 Rev 5"
AUTHORITY_LEVEL = 5
EMBED_MODEL = "text-embedding-3-large"
_PARAM_RE = re.compile(r"\{\{\s*insert:\s*param,\s*([^}\s]+)\s*\}\}")
_NS = uuid.UUID("11111111-2222-3333-4444-555555555555")  # deterministic id namespace


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _det_id(*parts: str) -> str:
    return str(uuid.uuid5(_NS, "/".join(parts)))


def _label(node: dict[str, Any]) -> str:
    for p in node.get("props", []):
        if p.get("name") == "label" and p.get("class") != "zero-padded":
            return p["value"]
    for p in node.get("props", []):
        if p.get("name") == "label":
            return p["value"]
    return node.get("id", "").upper()


def _param_map(control: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for prm in control.get("params", []):
        pid = prm.get("id", "")
        if prm.get("select"):
            sel = prm["select"]
            how = sel.get("how-many", "one")
            choices = "; ".join(sel.get("choice", []))
            out[pid] = f"[Selection ({how}): {choices}]"
        elif prm.get("label"):
            out[pid] = f"[Assignment: organization-defined {prm['label']}]"
        elif prm.get("values"):
            out[pid] = ", ".join(str(v) for v in prm["values"])
        else:
            out[pid] = "[Assignment: organization-defined parameter]"
    return out


def _subst(prose: str, params: dict[str, str]) -> str:
    return _PARAM_RE.sub(lambda m: params.get(m.group(1), "[organization-defined parameter]"), prose or "")


def _render_parts(parts: list[dict[str, Any]], params: dict[str, str], depth: int, lines: list[str]) -> None:
    for part in parts:
        name = part.get("name")
        if name in ("assessment-objective", "assessment-method", "objective"):
            continue
        plabel = ""
        for p in part.get("props", []):
            if p.get("name") == "label":
                plabel = p["value"]
                break
        prose = _subst(part.get("prose", ""), params)
        if prose or plabel:
            prefix = "  " * depth + (f"{plabel} " if plabel else "")
            lines.append(f"{prefix}{prose}".rstrip())
        _render_parts(part.get("parts", []), params, depth + 1, lines)


def _control_text(control: dict[str, Any], label: str) -> str:
    params = _param_map(control)
    statement_lines: list[str] = []
    guidance = ""
    for part in control.get("parts", []):
        if part.get("name") == "statement":
            _render_parts([part], params, 0, statement_lines)
        elif part.get("name") == "guidance":
            g: list[str] = []
            _render_parts([part], params, 0, g)
            guidance = "\n".join(g).strip()
    title = control.get("title", "")
    blocks = [f"{label} {title}".strip()]
    body = "\n".join(line for line in statement_lines if line.strip()).strip()
    if body:
        blocks.append("Control:\n" + body)
    if guidance:
        blocks.append("Discussion:\n" + guidance)
    text = "\n\n".join(blocks)
    return text[:6000]


def _is_withdrawn(control: dict[str, Any]) -> bool:
    for p in control.get("props", []):
        if p.get("name") == "status" and p.get("value") == "withdrawn":
            return True
    return False


def _iter_controls(controls: list[dict[str, Any]]):
    """Yield (control, label) for every active base control and nested enhancement.

    Withdrawn controls (e.g. AC-13) are stubs that only point at their successors
    and add retrieval noise, so they're skipped.
    """
    for c in controls:
        if not _is_withdrawn(c):
            yield c, _label(c)
        yield from _iter_controls(c.get("controls", []))


def _csrc_url(label: str) -> str:
    return (
        "https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/"
        f"SP_800_53_5_1_1/home?element={label.replace(' ', '')}"
    )


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 1_000_000:
        print(f"downloading catalog -> {path}")
        urllib.request.urlretrieve(CATALOG_URL, path)
    return json.loads(path.read_text(encoding="utf-8"))["catalog"]


def build_docs(catalog: dict[str, Any], tenant_id: str, limit: int | None) -> tuple[list, list, list]:
    policies: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    embeddings: list[dict[str, Any]] = []

    for group in catalog.get("groups", []):
        fam = group["id"].upper()
        fam_title = group["title"]
        policy_id = _det_id("policy", fam)
        version_id = _det_id("version", fam)
        policy_name = f"NIST SP 800-53 Rev 5 — {fam_title} ({fam})"

        controls = list(_iter_controls(group.get("controls", [])))
        if limit:
            controls = controls[:limit]

        version_doc = {
            "id": version_id,
            "version_number": 1,
            "version_label": "Rev 5",
            "title": fam_title,
            "effective_date": EFFECTIVE_DATE,
            "blob_container": "",
            "blob_name": "",
            "content_sha256": "",
            "metadata_json": {"source": "NIST SP 800-53 Rev 5", "family": fam},
            "metadata_sha256": "",
            "parse_status": "ready",
            "is_current": True,
            "parse_status_updated_at": _now(),
            "parse_error_code": None,
            "parse_error_message": None,
            "created_at": _now(),
            "correlation_id": None,
        }
        policies.append({
            "id": policy_id,
            "tenant_id": tenant_id,
            "external_id": f"nist-800-53-{fam.lower()}",
            "name": policy_name,
            "status": "active",
            "jurisdiction": "US Federal",
            "category": CATEGORY,
            "authority_level": AUTHORITY_LEVEL,
            "department_scope": "all",
            "policy_type": "security_control_catalog",
            "current_version_id": version_id,
            "created_by_user_id": None,
            "updated_by_user_id": None,
            "created_at": _now(),
            "updated_at": _now(),
            "versions": [version_doc],
        })

        for idx, (control, label) in enumerate(controls):
            text = _control_text(control, label)
            if not text.strip():
                continue
            section_id = _det_id("section", fam, control["id"])
            sha = _sha(text)
            sections.append({
                "id": section_id,
                "tenant_id": tenant_id,
                "policy_version_id": version_id,
                "section_index": idx,
                "section_path": label,
                "title": control.get("title", ""),
                "text": text,
                "start_offset": 0,
                "end_offset": len(text),
                "content_sha256": sha,
                "created_at": _now(),
            })
            embeddings.append({
                "id": _det_id("embedding", fam, control["id"]),
                "tenant_id": tenant_id,
                "policy_id": policy_id,
                "policy_version_id": version_id,
                "policy_section_id": section_id,
                "embedding_model": EMBED_MODEL,
                "policy_name": policy_name,
                "section_title": control.get("title", ""),
                "section_path": label,
                "section_index": idx,
                "text": text,
                "authority_level": AUTHORITY_LEVEL,
                "department_scope": "all",
                "policy_type": "security_control_catalog",
                "is_current": True,
                "effective_date": EFFECTIVE_DATE,
                "public_url": _csrc_url(label),
                "content_sha256": sha,
                "created_at": _now(),
                # 'embedding' vector filled in after embedding
            })

    return policies, sections, embeddings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(Path.home() / "nist_catalog.json"))
    ap.add_argument("--tenant", default="00000000-0000-0000-0000-000000000001")
    ap.add_argument("--limit", type=int, default=None, help="controls per family (testing)")
    args = ap.parse_args()

    catalog = load_catalog(Path(args.catalog))
    policies, sections, embeddings = build_docs(catalog, args.tenant, args.limit)
    print(f"built {len(policies)} policies, {len(sections)} sections, {len(embeddings)} embeddings")

    print("embedding section texts...")
    texts = [e["text"] for e in embeddings]
    vectors = embed_texts(texts)
    assert len(vectors) == len(embeddings), f"embedding count mismatch {len(vectors)} != {len(embeddings)}"
    for e, v in zip(embeddings, vectors):
        e["embedding"] = v
    print(f"embedded {len(vectors)} texts (dim={len(vectors[0])})")

    client = CosmosClient(os.environ["COSMOS_ENDPOINT"], os.environ["COSMOS_KEY"])
    db = client.get_database_client(os.environ.get("COSMOS_DATABASE", "policydb"))
    pol_c = db.get_container_client("policies")
    sec_c = db.get_container_client("sections")
    emb_c = db.get_container_client("embeddings")

    for p in policies:
        pol_c.upsert_item(p)
    print(f"upserted {len(policies)} policies")
    for i, s in enumerate(sections, 1):
        sec_c.upsert_item(s)
        if i % 200 == 0:
            print(f"  sections {i}/{len(sections)}")
    print(f"upserted {len(sections)} sections")
    for i, e in enumerate(embeddings, 1):
        emb_c.upsert_item(e)
        if i % 200 == 0:
            print(f"  embeddings {i}/{len(embeddings)}")
    print(f"upserted {len(embeddings)} embeddings")
    print("DONE")


if __name__ == "__main__":
    main()
