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
