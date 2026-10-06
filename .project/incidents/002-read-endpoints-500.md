# INC-002 — three production read endpoints return 500

**Status:** 🟡 fixed in code + tested, **not deployed**
**Opened:** 2026-10-06 · Found while preparing S3's crosswalk pass
**Severity:** Medium — references panel and version history broken; ask works

## Found by sweeping, not by reading code

A code search for routers bound to the Postgres-only `get_db` found one file.
A live sweep of every read endpoint with **real IDs from Cosmos** found three
failures, one of them a different bug the search could not have caught:

```
200  GET /v1/policies
500  GET /v1/policies/{id}/versions                 ← different root cause
200  GET /v1/policy-versions/{id}/sections
200  GET /v1/policy-sections/{id}
500  GET /v1/policy-sections/{id}/references
500  GET /v1/policy-versions/{id}/references
200  GET /v1/audit/{id}
```

## Root cause A — references router never ported to Cosmos

Logs: `AttributeError: 'NoneType' object has no attribute 'execute'` in
`references_repo.py`. `apps/api/routers/references.py` took a SQLAlchemy
session from `get_db` (`None` under `DB_BACKEND=cosmos`) and called module-level
Postgres helpers. Same defect class as INC-001's ingestion path.

**Fix:** router now uses `RepositorySet.references` via `get_repositories`.

**Parity gap found along the way:** Postgres hydrates `target_section_title`,
`target_section_path`, `target_policy_name`; Cosmos left all three `None`, so a
bare port would have stopped the 500 but shown UUIDs instead of
"AC-2 Account Management". Added `CosmosReferenceRepository._hydrate` — at most
one query per container regardless of reference count.

**Verified against live Cosmos** (read-only): `section_exists_for_tenant` →
True; `list_for_policy_version` → `[]` (container is empty, see S3 Finding 2);
`_hydrate` on a real target → `AC-2(3) | Disable Accounts | NIST SP 800-53 Rev 5 —
Access Control (AC)`. The fakes could not prove the `ARRAY_CONTAINS(@ids, c.id)`
query is valid Cosmos SQL; the live call does.

## Root cause B — catalog-seeded versions have no source blob

Logs: `ValueError: container_name must be non-empty`. The NIST seed writes
versions with `blob_container: ""` (they come from the OSCAL catalog, not an
upload). `list_policy_versions` built a blob URL for every version
unconditionally, so one seeded version 500'd the entire list.

**Fix:** `raw_blob_uri` is `None` when the version has no source file — the
field was already `Optional[str] = None` in `PolicyVersionResponse`.

## Tests

- `tests/unit/test_references_api.py` (6) — incl. a regression that the router
  works when `get_db` yields `None`, the production condition.
- `tests/unit/test_cosmos_repos.py` (+3) — hydration, one-query-per-container.
- `tests/unit/test_policies_api.py` (2) — mutation-checked: fail with the fix
  reverted, pass with it.

Suite 306 → **317**.

## Remaining Postgres-only API path

After this, `get_ingestion_service` (`apps/api/deps.py:60-65`) is the only one
left — uploads still fail on production. That is Phase 2 of the parked Cosmos
cutover and is larger than a router port.
