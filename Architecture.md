# PolicyPlatform Backend — Architecture

**A compliance-grade policy intelligence engine.** Ask a plain-English question about
your security and compliance obligations and get an answer grounded *only* in your
authoritative policy text — with the exact controls cited, a confidence score, a
refusal when evidence is thin, and a full audit trail. This document describes how the
backend is put together: the components, the two request pipelines, the data layer, and
the deployment topology.

> Scope: this file documents the `policy-back` repository. The React frontend
> (`apps/web`, built and served from the API image), the `policy-migrator`, and the
> `ohio_docs_ingestor` CLI are described only where they touch the backend.

---

## 1. System at a glance

```
                          ┌───────────────────────────────────────────────┐
   Browser / API client   │                  FastAPI API                  │
        │                 │            apps/api/main.py                    │
        │  HTTPS           │  routers: health ingest policies sections     │
        └────────────────▶│           references ask audit                 │
                          │  + serves built React SPA (apps/web/dist)      │
                          └───────┬───────────────────────┬───────────────┘
                                  │                        │
                    register/upload│                asks   │
                                  ▼                        ▼
              ┌──────────────────────────┐     ┌───────────────────────────┐
              │      Blob Storage        │     │       Ask / RAG pipeline  │
              │  policy-raw (uploads)    │     │  retrieve → rank → answer │
              │  policy-extracted        │     │           → audit         │
              └──────────┬───────────────┘     └───────────┬───────────────┘
                         │ enqueue                          │
                         ▼                                  │
              ┌──────────────────────────┐                 │
              │   Storage Queue          │                 │
              │   policy-extraction      │                 │
              └──────────┬───────────────┘                 │
                         │ dequeue                          │
                         ▼                                  │
              ┌──────────────────────────┐                 │
              │      Worker              │                 │
              │  apps/worker/main.py     │                 │
              │  extract → section →     │                 │
              │  embed → references      │                 │
              └──────────┬───────────────┘                 │
                         │                                  │
                         ▼            reads/writes          ▼
              ┌──────────────────────────────────────────────────────────┐
              │            Data layer (repository-abstracted)             │
              │   PostgreSQL 16 + pgvector   │   Azure Cosmos DB (NoSQL)  │
              │   HNSW cosine VECTOR(3072)   │   DiskANN cosine vector    │
              └──────────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────────────┐
              │   Azure OpenAI           │
              │  text-embedding-3-large  │
              │  GPT chat (answers)      │
              └──────────────────────────┘
```

The system has **two long-lived processes** (API and worker), a set of **backing
services** (database, blob, queue, Azure OpenAI), and a **repository abstraction** that
lets the exact same application code run on PostgreSQL/pgvector *or* Azure Cosmos DB.

---

## 2. Processes

### 2.1 API — `apps/api`

FastAPI application built by `create_app()` in [apps/api/main.py](apps/api/main.py).

- **App factory** configures structured logging, loads `ApiConfig.from_env()`, installs
  `RequestContextMiddleware` (correlation IDs) and CORS, and registers routers.
- **Routers** ([apps/api/routers/](apps/api/routers/)):
  | Router | Responsibility |
  |--------|----------------|
  | `health` | liveness/readiness |
  | `ingest` | create ingest batches, mint SAS upload URLs, register uploaded policies |
  | `policies` | list/read policies + versions |
  | `sections` | read extracted sections |
  | `references` | read extracted/resolved cross-references |
  | `ask` | the RAG endpoint — question in, grounded answer + citations out |
  | `audit` | read the immutable audit log |
- **Request/response contracts** live in [apps/api/schemas/](apps/api/schemas/) (HTTP
  edge) and [packages/core/dtos.py](packages/core/dtos.py) (internal RAG contracts).
- **SPA hosting** — if `apps/web/dist` exists in the image, the API mounts `/assets` and
  serves `index.html` for any unmatched path (client-side routing fallback). One
  container serves both the REST API and the console UI.

### 2.2 Worker — `apps/worker`

Queue-driven background processor. Entrypoint [apps/worker/main.py](apps/worker/main.py)
→ `run_worker_forever()` in `policy_processor.py`. It long-polls the
`policy-extraction` queue and runs the ingestion pipeline for each message. Discrete
jobs live in [apps/worker/jobs/](apps/worker/jobs/):

| Job | Purpose |
|-----|---------|
| `extract_policy` | pull raw blob → parse → section → persist |
| `embed_sections` / `embed_backfill` | embed sections into the vector store |
| `ref_backfill` | extract + resolve cross-references over the corpus |
| `sync_azure_search` | (optional) push sections to Azure Cognitive Search |

---

## 3. Domain packages — `packages/`

The business logic is factored into cohesive packages, kept independent of the FastAPI
and worker shells so both processes share them.

| Package | Responsibility |
|---------|----------------|
| `core` | DTOs, config, constants, logging, request context, small utils |
| `db` | ORM models, session, and the **repository abstraction** (PG + Cosmos impls) |
| `storage` | Blob service (uploads, extracted artifacts, SAS) + Azurite helpers |
| `queue` | Queue publisher/consumer + message contracts |
| `ingestion` | Ingestion service, dedupe, validators |
| `extraction` | PDF/DOCX/TXT parsers, text cleaner, sectioning, reference extract/resolve |
| `embeddings` | Azure OpenAI embedding client |
| `retrieval` | Retriever providers (FTS, pgvector, hybrid, Cosmos) + selection factory |
| `ranking` | Department-first bucket ranker, conflict + scoring helpers |
| `rag` | `AskService` / `AnswerService` orchestration, citation enforcer, prompts |
| `governance` | Audit service, evidence export, prompt registry, replay |
| `llm` | Azure OpenAI chat client with graceful excerpt fallback + safety |

---

## 4. Pipeline A — Ingestion (write path)

```
Client                 API                    Blob            Queue          Worker                 Data layer
  │  create batch       │                       │               │              │                        │
  ├────────────────────▶│  batch row            │               │              │                        │
  │  request upload URL  │                       │               │              │                        │
  ├────────────────────▶│  mint SAS ───────────▶│               │              │                        │
  │  PUT file (SAS)      │                       │  policy-raw   │              │                        │
  ├──────────────────────────────────────────▶ │               │              │                        │
  │  register policy     │                       │               │              │                        │
  ├────────────────────▶│  policy + version ────┼──────────────▶│ enqueue      │                        │
  │                      │                       │               ├─────────────▶│ dequeue                │
  │                      │                       │               │              │ parse (pdf/docx/txt)   │
  │                      │                       │               │              │ clean + section        │
  │                      │                       │               │              │ persist sections ─────▶│
  │                      │                       │               │              │ embed sections ───────▶│ (vector store)
  │                      │                       │               │              │ extract+resolve refs ─▶│
  │  poll status         │                       │               │              │ mark version ready     │
  ◀──────────────────────ready                   │               │              │                        │
```

1. **Batch + upload** — client creates an ingest batch, receives a short-lived SAS URL,
   and uploads the raw file straight to Blob Storage (`policy-raw`). The API never
   streams file bytes.
2. **Register** — client registers the uploaded blob as a policy version; the API writes
   the policy/version rows and enqueues an extraction message on `policy-extraction`.
3. **Extract** — the worker dequeues, pulls the raw blob, dispatches to the right parser
   ([packages/extraction/parsers/](packages/extraction/parsers/)), runs the cleaner, and
   splits into sections ([sectioning.py](packages/extraction/sectioning.py)).
4. **Embed** — each section is embedded via `text-embedding-3-large` and written to the
   vector store (pgvector `policy_embeddings` HNSW cosine, or Cosmos vector container).
5. **Cross-references** — the reference extractor/resolver finds and resolves inter-policy
   references ("see Section 3.2", "per HIPAA §164"), persisted for the `references` API.
6. **Ready** — the version is marked ready; the client's status poll flips to ready.

---

## 5. Pipeline B — Ask / RAG (read path)

Orchestrated by [`AskService`](packages/rag/ask_service.py) →
[`AnswerService`](packages/rag/answer_service.py): **retrieve → bucket → rank → answer →
audit**.

```
AskRequest ─▶ retrieve (hybrid: FTS ∪ vector) ─▶ department bucketing
           ─▶ rank primary/secondary          ─▶ confidence gate
           ─▶ grounded LLM synthesis (cite-or-refuse)
           ─▶ AnswerResponse (+ citations, decision, retrieval_log, secondary evidence)
           ─▶ audit write ─▶ audit_id stamped on response
```

1. **Retrieve** — `build_retriever()` selects the provider by backend/config and returns
   up to `max(EMBEDDINGS_TOP_K, FTS_TOP_K)` candidates.
2. **Department bucketing** — candidates split into three buckets by `department_scope`
   metadata: the user's department (A), org-wide `all` (B), and other departments (C).
   Selection is **department-first**: A wins if it has matches, else B, else C. The
   losing buckets become *secondary evidence* so cross-department conflicts surface
   rather than hide.
3. **Rank** — [`PolicyRanker`](packages/ranking/ranker.py) orders each bucket by
   relevance/authority/recency.
4. **Confidence gate** — if there is no primary evidence, or the top score is below
   `ANSWER_REFUSAL_MIN_SCORE` (default **0.5**), the service **refuses** with a fixed
   phrase and `refusal_reason="insufficient_evidence"` — it does not answer from general
   knowledge.
5. **Answer** — the top ~5 ranked candidates are handed to the LLM with a strict
   cite-or-refuse system prompt (from the governance prompt registry, with a hard-coded
   fallback). If the LLM is unavailable or errors, the service falls back to returning a
   clipped **excerpt** of the top evidence with an inline citation — the endpoint never
   hard-fails on LLM outage.
6. **Respond** — `AnswerResponse` carries the answer, `citations` (string handles),
   `citation_items` (structured), a `DecisionInfo` explaining bucket selection, a
   `retrieval_log` with hybrid counters, `secondary_evidence`, and `confidence`.
7. **Audit** — `AuditService` writes an immutable record of the exchange; the resulting
   `audit_id` is stamped onto the returned response.

---

## 6. Retrieval architecture

Selected at runtime by [packages/retrieval/factory.py](packages/retrieval/factory.py),
keyed first on `DB_BACKEND`, then on `RETRIEVER_BACKEND` for PostgreSQL.

| Backend | Provider | Notes |
|---------|----------|-------|
| `DB_BACKEND=cosmos` | `CosmosVectorRetriever` | DiskANN cosine vector query over Cosmos containers |
| PG · `RETRIEVER_BACKEND=pgsql_fts` | `PgsqlFtsRetriever` | Postgres full-text search |
| PG · `pgvector` | `PgVectorRetriever` | pgvector HNSW cosine over `policy_embeddings` |
| PG · `hybrid` *(default)* | `HybridRetriever` | merges vector + FTS candidate sets |
| Azure Search | `azure_search_provider` | **stub** — returns `[]` |

Guardrails: if `EMBEDDINGS_ENABLED` is true but the Azure OpenAI embedding config is
incomplete, the factory silently degrades embeddings off and falls back to FTS, so a
misconfigured environment still serves answers instead of erroring.

The hybrid retriever attaches debug counters (`hybrid_fts_candidates`,
`hybrid_vector_candidates`, `hybrid_merged_candidates`, …) to candidate metadata;
`AnswerService` lifts these into the response `retrieval_log` for observability.

---

## 7. Data layer & backend abstraction

The application never talks to a database driver directly. It depends on **repository
interfaces** ([packages/db/repositories/base.py](packages/db/repositories/base.py)) —
`IPolicyRepository`, `IPolicyVersionRepository`, `IPolicySectionRepository`,
`IEmbeddingRepository`, `IReferenceRepository`, `IAuditRepository`,
`IIngestBatchRepository`, `IIngestItemRepository` — bundled into a `RepositorySet`.

[`build_repositories()`](packages/db/repositories/factory.py) returns the correct
implementation set based on `DB_BACKEND`:

- **`postgresql`** (default) — SQLAlchemy 2.x `Pg*Repository` classes over a session.
- **`cosmos`** — `build_cosmos_repos()` over an `azure.cosmos.CosmosClient`.

This is what lets the same routers, worker jobs, and RAG services run unchanged on either
store. (Note: Cosmos moves sections into a standalone container to stay under the 2 MB
item limit.)

### PostgreSQL schema (Alembic — head `007`)

Migrations in [migrations/versions/](migrations/versions/); models in
[packages/db/models/](packages/db/models/).

| # | Migration | Adds |
|---|-----------|------|
| 001 | init | tenants, users, policies, policy_versions, policy_sections, ingest_batches |
| 002 | version_lineage | version lineage fields |
| 003 | audit_logs | audit log table |
| 004 | policy_ranking_fields | authority_level, department_scope, policy_type |
| 005 | enable_pgvector | `CREATE EXTENSION vector` |
| 006 | policy_embeddings | `policy_embeddings` table + HNSW cosine index, `VECTOR(3072)` |
| 007 | policy_references | cross-reference table |

---

## 8. Governance & audit

Compliance-grade behavior is a first-class concern, not an afterthought:

- **Immutable audit** — every ask is written by
  [`AuditService`](packages/governance/audit_service.py) and readable via the `audit`
  router.
- **Prompt registry** — versioned system prompts
  ([prompt_registry.py](packages/governance/prompt_registry.py)); the answer service
  requests `strict_citation` `v2` and falls back to a hard-coded prompt if the registry
  is unavailable.
- **Replay & evidence export** — [replay.py](packages/governance/replay.py) and
  [evidence_export.py](packages/governance/evidence_export.py) support reconstructing and
  exporting the evidence behind an answer.
- **Refuse-over-hallucinate** — the confidence gate (§5.4) is the core trust property:
  no grounding ⇒ explicit refusal.

---

## 9. Configuration

Environment-driven (`.env` locally; Key Vault + container app env in Azure). Key knobs:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DB_BACKEND` | `postgresql` | `postgresql` \| `cosmos` |
| `RETRIEVER_BACKEND` | `hybrid` | `pgsql_fts` \| `pgvector` \| `hybrid` (PG only) |
| `EMBEDDINGS_ENABLED` | `true` | toggle vector retrieval; auto-off if OpenAI config missing |
| `EMBEDDINGS_TOP_K` / `FTS_TOP_K` | `40` / `40` | candidate pool sizes |
| `EMBEDDING_DIM` | `3072` | must match `text-embedding-3-large` |
| `ANSWER_REFUSAL_MIN_SCORE` | `0.5` | refuse below this top-evidence score |
| `AZURE_OPENAI_ENDPOINT` / `_API_KEY` / `_API_VERSION` | — | Azure OpenAI access |
| `AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT` | — | embedding deployment name |
| `DATABASE_URL` | — | Postgres DSN (psycopg) |
| `COSMOS_DATABASE` | `policydb` | Cosmos database name |

---

## 10. Deployment topology

### Local — `docker-compose.yml`

| Service | Host port | Image / notes |
|---------|-----------|---------------|
| API | **8001** → 8000 | built from root `Dockerfile`; serves REST + SPA |
| worker | — | same image, `python -m apps.worker.main` |
| postgres | 5433 → 5432 | `pgvector/pgvector:pg16` |
| azurite | 10000/10001/10002 | blob / queue / table emulator |

Inside the compose network, API and worker reach Postgres and Azurite by service name;
the API still mints **host-accessible** SAS URLs (`127.0.0.1:10000`) so a browser client
can upload directly. Swagger: `http://localhost:8001/docs`.

> Rebuild gotcha: use `docker compose up -d --build api worker` after backend changes —
> a plain `up -d` reuses the cached image and masks code changes.

### Cloud — Azure

| Layer | Service |
|-------|---------|
| Frontend | React + MUI on Azure Static Web Apps (or served from the API image) |
| API | FastAPI on Azure Container Apps |
| Worker | Queue-driven worker on Azure Container Apps |
| Database | Azure Cosmos DB (NoSQL) with DiskANN cosine vector index |
| Embeddings / LLM | Azure OpenAI (`text-embedding-3-large`, GPT chat) |
| Storage / queue | Azure Blob Storage + Storage Queues |
| Secrets | Azure Key Vault via managed identity |
| IaC / CI-CD | Bicep + GitHub Actions (OIDC federation, no stored cloud creds) |

The repository abstraction (§7) is what makes the local **PostgreSQL/pgvector** and cloud
**Cosmos DB** targets interchangeable.

---

## 11. Milestone history

| Phase | Delivered | Status |
|-------|-----------|--------|
| **1** | Ingestion batches, versioning, queue-driven worker, blob/queue, migrations 001–006 | ✅ |
| **2** | Ask endpoint, immutable audit, FTS retrieval | ✅ |
| **2.5** | pgvector + hybrid retrieval, department-first ranking, embedding backfill | ✅ |
| **2.6 / 2.7** | LLM graceful degradation, refusal threshold, `retrieval_log` in response, per-`policy_id` cap | ✅ |
| **3.1** | Cross-reference extraction + resolution end-to-end, reference backfill job (migration 007) | ✅ |
| **3.1-redesign** | Repository abstraction + Cosmos DB NoSQL backend, backend-agnostic API + worker, Cosmos vector retrieval, NIST 800-53 seed, Azure OpenAI chat wired, CORS + SPA fallback | ✅ (current branch) |
| **3.2** | Conflict detection between policies | ⏸ parked |

**Reference corpus:** NIST SP 800-53 Rev 5 — 20 control families, 1,014 controls +
enhancements, loaded by a committed seed tool ([tools/seed_nist_800_53.py](tools/seed_nist_800_53.py))
from its public-domain OSCAL source.

---

## 12. Known gaps / non-goals

| Area | State |
|------|-------|
| Azure Cognitive Search retriever | ❌ stub — returns `[]` |
| Real AuthN / AuthZ | ❌ `tenant_id` comes from the client, not from verified auth claims |
| Approvals workflow | ❌ router present but not implemented |
| Conflict detection (Phase 3.2) | ⏸ parked |

---

## 13. Map — where to look

| I want to… | Start here |
|------------|-----------|
| See how the app is wired | [apps/api/main.py](apps/api/main.py) |
| Understand the RAG flow | [packages/rag/answer_service.py](packages/rag/answer_service.py) |
| Change retrieval behavior | [packages/retrieval/factory.py](packages/retrieval/factory.py) |
| Swap the database | [packages/db/repositories/factory.py](packages/db/repositories/factory.py) |
| Change ranking | [packages/ranking/ranker.py](packages/ranking/ranker.py) |
| Inspect API contracts | [packages/core/dtos.py](packages/core/dtos.py) |
| Trace the worker | [apps/worker/policy_processor.py](apps/worker/policy_processor.py) |
| Review the schema | [migrations/versions/](migrations/versions/) |
