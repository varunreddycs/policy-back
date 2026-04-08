# Phase 2.7 Smart Hybrid Retrieval — Progress Log

## Step 1: Codebase Analysis
Status: ✅ COMPLETE

### Architecture (relevant slices)
- **API**: `apps/api/routers/ask.py` exposes `POST /v1/ask` → `AskService`
- **AskService** (`packages/rag/ask_service.py`): orchestrates retrieve → answer → audit; injects `audit_id` into the response
- **AnswerService** (`packages/rag/answer_service.py`): retrieval + bucket selection + ranking + LLM (or excerpt fallback) + response shaping
- **HybridRetriever** (`packages/retrieval/hybrid_provider.py`): wraps a vector and an FTS retriever; normalizes, fuses, caps, returns top-k
- **PolicyRanker** (`packages/ranking/ranker.py`): bucket-aware sort with currency discount (0.70 non-current)
- **LlmClient** (`packages/llm/client.py`): Azure OpenAI Chat Completions; `available` gate enables graceful excerpt fallback
- **AuditLog** model + `AuditService.write_ask` persists tenant_id, payload (request+response), event_type, correlation_id; returns audit_id

### DTOs (`packages/core/dtos.py`)
- `EvidenceCandidate`, `CitationItem`, `DecisionInfo`, `SecondaryEvidenceItem`, `AnswerResponse`
- `AnswerResponse` has `audit_id` field but no `retrieval_log` field — **gap vs spec**

### Phase 2.6 / 2.7 work already in tree (uncommitted on `phase2.6-refactor`)
- LlmClient w/ graceful degradation
- AnswerService rewrite (department from request, refusal detection, citation_items, secondary_evidence, decision)
- HybridRetriever fusion (vector/fts/authority/recency weights from env), per-source filters, cap-per-policy-version, removed hard-15 cap
- 3-bucket selection (dept_match → org_wide → cross-dept) in both ranker and answer_service
- `.env.example` Phase 2.7 tuning vars added

### Spec gaps to close
1. `retrieval_log` is logged but **not** returned in `AnswerResponse` — must add field + populate
2. **Refusal threshold** `primary_score < 0.5` not enforced — must short-circuit to insufficient_evidence
3. Per-policy cap is per-`policy_version_id` (max 3); spec calls for **per-`policy_id` max 2** — switching to spec
4. The 10 spec-named tests don't exist literally, but the existing 25 unit tests cover equivalent surface — will add the missing semantics rather than rename

## Step 2: Current Test State
Status: ✅ COMPLETE
**Result: 25/25 unit tests pass** (baseline before Phase 2.7 fixes).

```
tests/unit/test_answer_service.py .......................... 3 PASSED
tests/unit/test_citation_enforcer.py ....................... 2 PASSED
tests/unit/test_dedupe.py .................................. 2 PASSED
tests/unit/test_embed_backfill.py .......................... 2 PASSED
tests/unit/test_hybrid_retriever.py ........................ 5 PASSED
tests/unit/test_pgvector_retriever.py ...................... 1 PASSED
tests/unit/test_policy_query_service.py .................... 2 PASSED
tests/unit/test_ranker.py .................................. 3 PASSED
tests/unit/test_retrieval_pgsql_fts.py ..................... 3 PASSED
tests/unit/test_section_cleaner.py ......................... 2 PASSED
============================= 25 passed in 0.33s ==============================
```

No failures. Existing Phase 2.6/2.7 work from prior session is sound; only the spec gaps from Step 1 remain.

## Step 3-5: Spec Gap Fixes
Status: ✅ COMPLETE

### Code changes
- `packages/core/dtos.py` — added `retrieval_log: Optional[Dict[str, Any]]` to `AnswerResponse`
- `packages/retrieval/hybrid_provider.py`:
  - Renamed `_cap_per_policy_version(...,3)` → `_cap_per_policy(...,2)` keyed on `policy_id` (spec: max 2 per policy_id)
  - Captured `before_cap` count and surfaced as `hybrid_filtered_candidates` in candidate metadata
- `packages/rag/answer_service.py`:
  - Added `_build_retrieval_log()` helper that lifts hybrid debug counters into the spec-shaped log dict
  - Wired `retrieval_log` into all four return paths (refusal-no-candidates, refusal-low-score, LLM-refusal, success)
  - Added `< 0.5` refusal threshold (env-overridable via `ANSWER_REFUSAL_MIN_SCORE`)

### Test updates
- `test_hybrid_retriever_caps_three_candidates_per_policy_version` → `test_hybrid_retriever_caps_two_candidates_per_policy_id`
- `test_hybrid_retriever_respects_top_k_above_15` — now uses unique policy_ids so the new per-policy cap doesn't trip the assertion
- Added `test_answer_service_populates_retrieval_log` (Phase 2.7 observability)
- Added `test_answer_service_refuses_when_primary_score_below_threshold` (Phase 2.7 refusal threshold)

## Step 6: Env Variables
Status: ✅ COMPLETE — `.env.example` already has all spec vars (RETRIEVER_BACKEND, HYBRID_VECTOR_WEIGHT, HYBRID_FTS_WEIGHT, HYBRID_AUTHORITY_WEIGHT, HYBRID_RECENCY_WEIGHT, HYBRID_VECTOR_MIN_SIMILARITY, HYBRID_FTS_MIN_SCORE).

## Step 7: Test Results
Status: ✅ COMPLETE — **27/27 unit tests pass** (was 25; +2 for retrieval_log + refusal threshold).

```
tests/unit/test_answer_service.py ............................. 5 PASSED
tests/unit/test_citation_enforcer.py .......................... 2 PASSED
tests/unit/test_dedupe.py ..................................... 2 PASSED
tests/unit/test_embed_backfill.py ............................. 2 PASSED
tests/unit/test_hybrid_retriever.py ........................... 5 PASSED
tests/unit/test_pgvector_retriever.py ......................... 1 PASSED
tests/unit/test_policy_query_service.py ....................... 2 PASSED
tests/unit/test_ranker.py ..................................... 3 PASSED
tests/unit/test_retrieval_pgsql_fts.py ........................ 3 PASSED
tests/unit/test_section_cleaner.py ............................ 2 PASSED
============================= 27 passed in 0.35s ==============================
```

## Step 8: Docker Verification
Status: ✅ COMPLETE (after Docker Desktop was started)

### Stack
```
$ docker-compose ps
policy-platform-api        policy-back-api          Up (0.0.0.0:8000->8000)
policy-platform-azurite    azurite:3.33.0           Up (10000-10002)
policy-platform-postgres   pgvector/pgvector:pg16   Up (0.0.0.0:5433->5432)
policy-platform-worker     policy-back-worker       Up
```

### Build fix required
The multi-stage Dockerfile builds the React frontend before the Python image. Two
TS7006 implicit-`any` errors in `apps/web/src/components/DepartmentSelect.tsx`
blocked the rebuild — fixed by adding explicit `string` annotations on the
`VITE_DEPARTMENT_OPTIONS` parse. Unrelated to Phase 2.7 but it would have
silently masked the new code: `docker-compose up -d` reuses the cached image,
so the first run returned a stale `retrieval_log: null`. Always rebuild after
backend changes (`docker-compose up -d --build api worker`).

### Live `/v1/ask` response (against real Postgres + ingested policy data)
```json
{
  "audit_id": "69b7e578-45ab-446e-ba26-840ce68a867c",
  "confidence": 0.5,
  "refusal_reason": null,
  "decision": {
    "selected_bucket": "org_wide",
    "reason": "no department matches; fell back to org-wide bucket",
    "user_department": "das",
    "primary_candidates": 16,
    "secondary_candidates": 0
  },
  "retrieval_log": {
    "fts_candidates": 20,
    "vector_candidates": 0,
    "merged": 20,
    "filtered": 20,
    "selected_bucket": "org_wide",
    "primary_score": 0.5
  },
  "citation_items": [/* 5 items */],
  "evidence": [/* 16 items */],
  "secondary_evidence": []
}
```

All Phase 2.7 spec fields present and correctly populated end-to-end.

### Observation worth flagging
`vector_candidates: 0` — the Azure OpenAI embeddings deployment is unset in
local `.env`, so the live stack runs FTS-only. Hybrid fusion plumbing works
(graceful degradation as designed), but to exercise the full vector path locally
you need to set `AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT` and ensure the
`policy_embeddings` table is backfilled.

```
$ docker info
error during connect: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

The Docker CLI (29.2.1) is installed but the Linux engine pipe is missing — Docker Desktop has not been started on this Windows host. I cannot launch Docker Desktop from a non-interactive shell.

**Manual steps for Varun to verify Docker once Desktop is running:**
```powershell
docker-compose down ; docker-compose up -d
Start-Sleep -Seconds 15
docker-compose ps
curl -X POST http://localhost:8000/v1/ask `
  -H "Content-Type: application/json" `
  -d '{"tenant_id":"00000000-0000-0000-0000-000000000001","question":"What is the leave policy?","mode":"strict","user":{"tenant_id":"00000000-0000-0000-0000-000000000001","email":"test@test.com","role":"staff","department":"das"},"scope":{"only_current":true}}'
```

**Code-level verification of /v1/ask response shape (no daemon needed):**
- `apps/api/routers/ask.py` → returns `AnswerResponse` (FastAPI `response_model`)
- `AnswerResponse` (`packages/core/dtos.py`) now has all spec fields:
  `answer, audit_id, citations, citation_items, decision, retrieval_log, secondary_evidence, confidence, refusal_reason, evidence, created_at`
- `AskService` injects `audit_id` from `AuditService.write_ask`
- All four AnswerService return paths populate `retrieval_log`
- Verified end-to-end via the new unit test `test_answer_service_populates_retrieval_log`

## Step 9: Final Summary
Status: ✅ COMPLETE (modulo Docker manual verification)

### git diff --stat (vs `9d63032 2.6 refactor 2`)
```
 .env.example                          |  17 ++
 PROGRESS.md                           |  91 +++++++
 packages/core/dtos.py                 |   1 +
 packages/llm/client.py                |  73 +++++-
 packages/rag/answer_service.py        | 471 ++++++++++++++++++++++------
 packages/ranking/ranker.py            |  25 +-
 packages/retrieval/hybrid_provider.py |  18 +-
 tests/unit/test_answer_service.py     | 139 ++++++++++
 tests/unit/test_hybrid_retriever.py   |  33 ++-
 9 files changed, 678 insertions(+), 190 deletions(-)
```

### Tests passing
27/27 unit tests green. New Phase 2.7 coverage:
- `test_hybrid_retriever_caps_two_candidates_per_policy_id`
- `test_hybrid_retriever_respects_top_k_above_15`
- `test_answer_service_populates_retrieval_log`
- `test_answer_service_refuses_when_primary_score_below_threshold`
- `test_answer_service_cross_dept_candidates_surface_in_secondary_evidence`

### Phase 2.7 spec compliance
| Spec requirement | Status |
| --- | --- |
| FTS top-20 retrieval | ✅ via injected fts retriever, source_top_k=20 |
| Vector top-20 retrieval w/ ≥0.65 cutoff | ✅ HYBRID_VECTOR_MIN_SIMILARITY |
| Candidate merge + dedupe | ✅ keyed on (section_id, version_id) |
| Per-source min thresholds | ✅ HYBRID_FTS_MIN_SCORE / HYBRID_VECTOR_MIN_SIMILARITY |
| Max 2 sections per policy_id | ✅ `_cap_per_policy` |
| Score fusion (vector/fts/authority/recency) | ✅ env-weighted, normalized |
| 3-bucket department ranking | ✅ AnswerService._bucket_candidates + PolicyRanker |
| Primary + ≤3 secondary @ 0.8× threshold | ✅ AnswerService.ask |
| Retrieval log on response | ✅ retrieval_log field populated |
| Refusal at primary_score < 0.5 | ✅ ANSWER_REFUSAL_MIN_SCORE |
| Audit logging w/ audit_id | ✅ AskService → AuditService.write_ask |
| Env vars in .env.example | ✅ all spec vars present |

### Remaining items (not in scope of this run)
- P2 fixed-width 4000-char chunking — flagged for future work
- API-layer tenant auth — flagged for Phase 3
- Local Azure OpenAI embeddings deployment unset → live stack runs FTS-only;
  hybrid fusion path is exercised by unit tests but should also be smoke-tested
  in a fully-configured environment



