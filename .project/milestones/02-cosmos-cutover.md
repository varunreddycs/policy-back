# 02 — Cosmos-only cutover

**Phase 0: done (`fb84986`). Phases 1–6: parked 2026-10-05 at the user's request.**

Full plan: `C:\Users\varun\.claude\plans\i-want-you-to-giggly-boot.md`

## Why this exists

The migration already happened at the infrastructure layer and was never
finished in code. Verified against the live subscription:

| Fact | Evidence |
|---|---|
| Azure runs `DB_BACKEND=cosmos` | `infra/modules/containerapps.bicep:215,388` |
| Azure provisions no Postgres | `infra/main.bicep` never references `postgres.bicep` |
| Cosmos is not IaC-provisioned either | endpoint/key are input params; account made out-of-band |
| Account is **serverless** | `az cosmosdb show` → `EnableServerless`, `EnableNoSQLVectorSearch` |
| Vector index is correct | `embeddings`: DiskANN / cosine / 3072 dims |
| Local dev runs Postgres | `.env` sets no `DB_BACKEND` → falls through to default |

So Q1–Q7 and S1/S2/S5 were all built and verified against a backend production
does not run. That drift is the actual tech debt.

**On cost:** the expense is the SKU, not Postgres. `postgres.bicep` defaults to
`Standard_D2s_v3`/GeneralPurpose/128GB (~$180–260/mo). A Burstable B1ms is
~$20/mo. If cost were the only driver, one bicep parameter captures most of the
saving. The real argument for Cosmos is one backend instead of two.

## Phase 0 — done

Found an **active production data-loss bug** while planning.

Versions are a nested array inside the policy document and items inside the
batch document, so appending one element rewrites the whole document. All 15
`upsert_item` calls were unguarded → last-write-wins. Two concurrent writers
each read the same array; the second silently destroyed the first's element.

The failure was invisible end to end: the losing client already held a 201, the
queue message was in flight, and the worker then looked the version up, got
`None`, logged `policy_version_not_found` and returned. An accepted document
would never be processed, never be searchable, and raise no error anywhere.

Fix: 9 read-modify-write sites now replay under an `If-Match` precondition and
retry on 412. The other 6 upserts write standalone docs with fresh ids and
cannot contend (each verified individually, not assumed).

- `packages/db/repositories/cosmos/concurrency.py` — the `rmw` helper
- `packages/db/repositories/errors.py` — typed conflicts
- `tests/unit/test_cosmos_repos.py` — first ever direct Cosmos tests

Mutation-verified: disabling the ETag guard fails both race tests; restoring it
passes all 9. Suite went 274 → 283.

## Phases 1–6 — parked

| Phase | Work | Est. |
|---|---|---|
| 1 | Cosmos emulator in compose; `azure-cosmos` into local venv | 1d |
| 2 | Port `IngestionService` onto `RepositorySet` | 3d |
| 3 | Azure AI Search for lexical parity + eval gate | 2d |
| 4 | Remaining invariants (one-current-version, status validation) | 1–2d |
| 5 | Port backfill jobs | 1d |
| 6 | Delete PostgreSQL | 1d |

## Open items carried forward

- 🔴 **Ingestion is broken in Azure.** `apps/api/deps.py:63-65` passes
  `session=` with no Cosmos branch, unlike `get_repositories` directly above it.
  Under Cosmos `get_db_session` yields `None` → upload fails at
  `self._session.begin()`. **Possibly relevant to INC-001.**
- 🔴 **Leaked Cosmos primary key** in plaintext across three allowlist entries
  in `.claude/settings.local.json`. Needs rotating.
- 🟠 **No lexical retrieval on Cosmos.** `retrieval/factory.py` ignores
  `RETRIEVER_BACKEND` under Cosmos and returns a bare `CosmosVectorRetriever`,
  so Q5 RRF and Q7 hybrid never run in production. **Likely relevant to INC-001.**
- 🟠 `azure-cosmos` is in `requirements.txt:13` but missing from the local
  `.venv`, so the Cosmos path cannot be exercised locally.
- 🟡 Migrator's `ensure_schema()` omits the vector policy; harmless here because
  the app created the container first, but it would permanently break vector
  search in a fresh environment.

## Decision point

Phase 3's eval is both a quality gate and the strategy decision. If Azure AI
Search cannot match the tuned hybrid retrieval, a Burstable Postgres at ~$20/mo
with full transactions and real constraints may beat Cosmos + Search at ~$80/mo.
