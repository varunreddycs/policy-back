# PolicyPlatform Backend — Project Memory

## Quick Reference

| Task | Command |
|------|---------|
| Start full stack | `docker compose up -d --build` |
| Stop stack | `docker compose down` |
| View logs | `docker compose logs -f api` |
| Run migrations | `uv run alembic upgrade head` |
| Check migration | `uv run alembic current` |
| Run tests | `uv run pytest` |
| Format | `uv run ruff format .` |
| Lint | `uv run ruff check --fix .` |
| Type check | `uv run pyright` |
| Start worker only | `docker compose up -d worker` |

## Port Assignments

| Service | Host Port | Notes |
|---------|-----------|-------|
| API | **8001** | Changed from 8000 — Jarvis agent uses 8000 |
| Postgres | 5433 | pgvector/pgvector:pg16 |
| Azurite Blob | 10000 | devstoreaccount1 |
| Azurite Queue | 10001 | devstoreaccount1 |
| Azurite Table | 10002 | devstoreaccount1 |

Swagger UI: http://localhost:8001/docs

## Stack

- **FastAPI + Uvicorn** — `apps/api/main.py` (`create_app()`)
- **PostgreSQL 16 + pgvector** — primary store + vector similarity (`policy_embeddings`, HNSW cosine, VECTOR(3072))
- **Azure Blob Storage / Azurite** — raw policy uploads (`policy-raw`), extracted artifacts (`policy-extracted`)
- **Azure Storage Queue / Azurite** — background extraction trigger, queue: `policy-extraction`
- **SQLAlchemy 2.x + Alembic** — ORM in `packages/db/models/`, migrations in `migrations/versions/`
- **Pydantic v2** — all API contracts in `packages/core/dtos.py`
- **Azure OpenAI** — embeddings via `packages/embeddings/azure_openai_client.py`
- **structlog** — structured JSON logging throughout

## Migration State

Current head: **007_policy_references**

| # | Migration |
|---|-----------|
| 001 | init — tenants, users, policies, policy_versions, policy_sections, ingest_batches |
| 002 | version_lineage fields |
| 003 | audit_logs table |
| 004 | policy ranking fields (authority_level, department_scope, policy_type) |
| 005 | enable pgvector extension |
| 006 | policy_embeddings table + HNSW index |
| 007 | policy_references |

## Package Layout

```
apps/
  api/
    main.py          # FastAPI app factory; registers all routers
    deps.py          # FastAPI Depends providers
    routers/         # health, ingest, policies, sections, ask, audit, approvals
  worker/
    main.py          # Queue consumer entrypoint
    policy_processor.py
    jobs/embed_backfill.py

packages/
  core/dtos.py       # AskRequest, AnswerResponse, EvidenceCandidate, CitationItem, DecisionInfo
  rag/
    ask_service.py   # Phase 2 orchestration: retrieve → answer → audit
    answer_service.py
  retrieval/
    factory.py       # RETRIEVER_BACKEND switch: pgsql_fts | pgvector | hybrid
    hybrid_provider.py
    pgvector_provider.py
    pgsql_fts_provider.py
    azure_search_provider.py  # STUB — returns []
  ranking/ranker.py  # 3-bucket: dept_match → org_wide → cross_dept
  governance/audit_service.py
  extraction/
    extractor.py     # PDF/DOCX/TXT dispatch + 4000-char chunking
    cleaner.py       # normalize extracted text
  embeddings/azure_openai_client.py
  llm/client.py      # Azure OpenAI Chat Completions; graceful excerpt fallback
  storage/blob_service.py
  db/models/
```

## Retrieval Config (.env)

```
RETRIEVER_BACKEND=hybrid          # pgsql_fts | pgvector | hybrid
EMBEDDINGS_ENABLED=true
EMBEDDINGS_TOP_K=40
FTS_TOP_K=40
AZURE_OPENAI_ENDPOINT=https://mythri-resource.openai.azure.com
AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=text-embedding-3-large
EMBEDDING_DIM=3072
```

## Phase Completion Status

| Area | Status |
|------|--------|
| Phase 1 — ingestion, versioning, worker, blob/queue, migrations 001–006 | ✅ Done |
| Phase 2 — Ask endpoint, audit, FTS retrieval | ✅ Done |
| Phase 2.5 — pgvector + hybrid retrieval, department-first ranking, embedding backfill | ✅ Done |
| Phase 2.6/2.7 — LLM graceful degradation, refusal detection, retrieval_log in AnswerResponse | ✅ Done |
| Azure Search retriever | ❌ Stub (returns []) |
| Real AuthN/AuthZ | ❌ tenant_id from client, not from auth claims |
| Approvals router | ❌ Empty template |

## Unit Test Baseline

25/25 pass (last verified during Phase 2.7 work):

```
tests/unit/test_answer_service.py        3 passed
tests/unit/test_citation_enforcer.py     2 passed
tests/unit/test_dedupe.py                2 passed
tests/unit/test_embed_backfill.py        2 passed
tests/unit/test_hybrid_retriever.py      5 passed
tests/unit/test_pgvector_retriever.py    1 passed
tests/unit/test_policy_query_service.py  2 passed
tests/unit/test_ranker.py                3 passed
tests/unit/test_retrieval_pgsql_fts.py   3 passed
tests/unit/test_section_cleaner.py       2 passed
```

## Key DTOs (packages/core/dtos.py)

- `AskRequest` — query, tenant_id, department, user_context, top_k
- `AnswerResponse` — answer, citations (list[CitationItem]), decision (DecisionInfo), secondary_evidence, audit_id, retrieval_log
- `EvidenceCandidate` — section_id, policy_id, policy_version_id, score, text, metadata
- `CitationItem` — handle, policy_title, section_title, excerpt, authority_level
- `DecisionInfo` — verdict, confidence, reasoning

## Cosmos DB Migration (separate repo: policy-migrator)

A separate migrator project (`policy-migrator`) was built to migrate data from PostgreSQL to Azure Cosmos DB NoSQL. It lives outside this repo. Connection details in `.claude/settings.local.json` bash permissions.

## Notes

- Docker port 8001 is the canonical external port for this project (not 8000).
- The `docker compose up -d --build` exit code 1 on Windows is a PowerShell stderr rendering artifact — containers actually start successfully. Verify with `docker compose ps`.
- `.env` has Azurite default shared key hardcoded — this is intentional for local dev.
- `alembic upgrade head` with no output lines after "Will assume transactional DDL" = schema already at head.
- Cosmos DB endpoint and key are in `.claude/settings.local.json` for the migrator CLI permissions.
