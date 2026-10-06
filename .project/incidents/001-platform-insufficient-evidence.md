# INC-001 — platform.mistrv.com returns "insufficient_evidence" on every query

**Status:** ✅ **RESOLVED** 2026-10-05 — fix applied to both container apps and verified end to end
**Opened:** 2026-10-05 · **Closed:** 2026-10-05 (~25 min)
**Severity:** High — the product's core feature is unusable; no data loss
**Reported as:** "platform.mistrv.com is down"

## It is not down

| Check | Result |
|---|---|
| DNS | resolves → Azure Static Web Apps |
| `GET https://platform.mistrv.com` | **200 OK**, SPA shell serves correctly |
| `GET /health` on the API | **200 OK**, `{"status":"ok"}` |
| Container apps | `policy-api-dev` + `policy-worker-dev`, 1 replica each, Healthy |
| Worker | polling the queue normally |

Everything is up. Every answer is a refusal.

## Reproduced

```
POST https://policy-api-dev.purpleglacier-f66f3ddd.eastus2.azurecontainerapps.io/v1/ask
{"question":"What does AC-2 require for account management?", ...}

{"answer":"Insufficient evidence in available policy sections.",
 "confidence":0.0, "refusal_reason":"insufficient_evidence",
 "retrieval_log":{"fts_candidates":0,"vector_candidates":0,"merged":0,...}}
```

`vector_candidates: 0` and `fts_candidates: 0` — retrieval returns nothing at all.

(Note: the request field is `question`, not `query`. A `query` body 422s.)

## Root cause

Three environment variables on `policy-api-dev` are **empty strings**:

```
AZURE_OPENAI_ENDPOINT                 (empty)
AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT    (empty)
AZURE_OPENAI_CHAT_DEPLOYMENT          (empty)
AZURE_OPENAI_API_VERSION   = 2024-02-15-preview   ✓
AZURE_OPENAI_API_KEY       → secret azure-openai-api-key ✓
EMBEDDINGS_ENABLED         = true                 ✓
```

Verified in the live logs:

```
RuntimeError: Missing required environment variable: AZURE_OPENAI_ENDPOINT
  → packages/embeddings/azure_openai_client.py:17  _require_env
  → packages/retrieval/cosmos_vector_provider.py:172  _get_query_embedding
WARNING cosmos_vector.no_embedding_available
```

**Failure chain:** `EMBEDDINGS_ENABLED=true` → the Cosmos retriever tries to embed
the query → `_require_env` raises on the empty endpoint → the exception is
swallowed → `retrieve()` returns `[]` → zero candidates → the answer service
classifies it as a refusal and reports 0% confidence.

The config has been broken since the **2026-08-19** deployment (revision
`policy-api-dev--azd-1787145634`, 47 days old). This is almost certainly a
deployment-parameter gap, not a regression: `infra/main.bicep` takes
`azureOpenAiEndpoint` as a parameter defaulting to `''`, and nothing supplied it.

## The fix

`mythri-resource` (kind **AIServices**, rg `my-personal`) has the right models:

| Deployment | Model | Capacity |
|---|---|---|
| `text-embedding-3-large` | text-embedding-3-large | 500 |
| `gpt-5.2-chat` | gpt-chat-latest | 500 |

**Verified end to end before recommending** — a live embeddings call returned
**3072 dimensions**, matching `EMBEDDING_DIM=3072` and the Cosmos DiskANN index:

```
POST https://mythri-resource.cognitiveservices.azure.com/openai/deployments/
     text-embedding-3-large/embeddings?api-version=2024-02-15-preview
→ 200, embedding dims: 3072
```

**The deployed `azure-openai-api-key` secret already belongs to
`mythri-resource`** (verified by comparison against both accounts' keys). So the
credential is correct and in place; only the three plaintext vars are missing.

Values to set on `policy-api-dev` (and `policy-worker-dev`, which has the same
empty vars and needs them for embedding generation during ingestion):

```
AZURE_OPENAI_ENDPOINT              = https://mythri-resource.cognitiveservices.azure.com
AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT = text-embedding-3-large
AZURE_OPENAI_CHAT_DEPLOYMENT       = gpt-5.2-chat
```

⚠️ **The endpoint host is `cognitiveservices.azure.com`, not `openai.azure.com`.**
`mythri-resource` is an AIServices account. Both subagents initially proposed
`https://mythri-resource.openai.azure.com` — that host does not resolve for this
account. The embeddings client builds
`{endpoint}/openai/deployments/{deployment}/embeddings`, which is correct against
the AIServices host.

## Two caveats before declaring victory

1. **Unknown whether Cosmos actually holds embeddings.** If the `embeddings`
   container is empty, fixing the config yields working query embedding but
   still zero candidates. Verify document counts per container immediately after
   the fix. (A REST probe during this investigation failed only because the
   request was unsigned — that was a tooling error, not a finding.)
2. **No lexical fallback exists on Cosmos.** `fts_candidates: 0` is not a second
   symptom — `packages/retrieval/factory.py` ignores `RETRIEVER_BACKEND` entirely
   when `DB_BACKEND=cosmos` and returns a bare `CosmosVectorRetriever`. So vector
   search is the *only* retrieval path in production, with no degraded mode. This
   is the Phase 3 gap in [02-cosmos-cutover](../milestones/02-cosmos-cutover.md).

## Follow-ups this exposed

- 🟠 **Empty-string config passes startup silently.** The app boots healthy with
  `EMBEDDINGS_ENABLED=true` and no endpoint, then fails per-request. A startup
  assertion — if embeddings are enabled, the endpoint and deployment must be
  non-empty — would have surfaced this in August instead of October.
- 🟠 **The swallowed exception hid it.** `CosmosVectorRetriever.retrieve()`
  catches bare `Exception` and returns `[]`, so a config failure is
  indistinguishable from "no matching policies." Already logged as a Phase 4 item.
- 🟡 **`/health` is not a real health check.** It returned 200 throughout. A
  dependency-aware readiness probe would have caught this.
- 🟡 **`infra/main.bicep` defaults `azureOpenAiEndpoint` to `''`.** It should
  either be required or the app should refuse to start without it.


---

## Resolution — applied and verified

Set on **both** `policy-api-dev` and `policy-worker-dev`:

```
AZURE_OPENAI_ENDPOINT              = https://mythri-resource.cognitiveservices.azure.com
AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT = text-embedding-3-large
AZURE_OPENAI_CHAT_DEPLOYMENT       = gpt-5.2-chat
```

### Before

```
retrieval_log: {"fts_candidates":0,"vector_candidates":0,"merged":0,"filtered":0}
confidence: 0.0   refusal_reason: "insufficient_evidence"
```

### After

```
retrieval_log: {"merged":40,"filtered":40,"selected_bucket":"org_wide","primary_score":0.99}
confidence: 0.99  refusal_reason: null   citations: 5
```

Two independent queries return real grounded answers:

- *"What does access control AC-2 require for account management?"* → "AC-2
  Account Management requires organizations to define and document permitted and
  prohibited account types, assign account managers…" (5 citations)
- *"What are the requirements for multi-factor authentication IA-2?"* → "IA-2
  requires organizations to uniquely identify and authenticate organizational
  users…" (5 citations)

Both the embedding **and** chat deployments are working — these are
model-generated answers, not excerpt fallbacks.

Caveat 1 from above is now closed: Cosmos holds **20 policies, 1014 sections,
1014 embeddings, 80 audit logs**, all under tenant
`00000000-0000-0000-0000-000000000001`, with 3072-dim vectors and denormalized
text. A hand-run `VectorDistance` query returned AC-2 (0.6547), AC-2(1)
(0.6003), AC-2(8) (0.585).

### One false lead, recorded honestly

Immediately after the API update, a test still returned zero candidates and I
suspected the `department` filter. That was wrong — the container was still
warming on the new revision. Retesting across `operations`, `all`, `security`
and no-department all returned `merged=40`. **The department filter was never
implicated.** Worth recording so nobody optimizes a filter that works.

### Note on `fts_candidates: 0`

Still zero, and still expected: Cosmos has no lexical retrieval path at all
(`retrieval/factory.py` ignores `RETRIEVER_BACKEND` under Cosmos). Vector search
alone is now carrying the product. See Phase 3 in
[02-cosmos-cutover](../milestones/02-cosmos-cutover.md).

## Why this took 47 days to notice

The config broke at the 2026-08-19 deploy. Nothing alerted because:

1. `/health` returned 200 the entire time — it checks nothing downstream.
2. The retriever swallows exceptions into `[]`, so a config failure looks
   identical to "no matching policies."
3. A refusal is a *valid* product response, so the API returned 200 with a
   plausible-looking body on every query.

**The highest-value follow-up is not the config — it is making this class of
failure loud.** See the follow-ups above.
