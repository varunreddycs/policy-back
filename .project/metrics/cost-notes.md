# Cost

## Azure, as deployed

| Resource | Config | Est./mo |
|---|---|---|
| Cosmos DB `platformpolicycosmos` | **serverless**, 1 region | single-digit $ at current volume |
| Container Apps `policy-api-dev` | 1 replica | ~$15–30 |
| Container Apps `policy-worker-dev` | 1 replica | ~$15–30 |
| Static Web App | Standard | ~$9 |
| Azure OpenAI `mythri-resource` | per-token | usage-driven |
| **PostgreSQL** | **not provisioned in Azure** | **$0** |

`infra/modules/postgres.bicep` exists but `infra/main.bicep` never references
it. The orphaned module defaults to `Standard_D2s_v3` / GeneralPurpose / 128GB
(~$180–260/mo) — that is the figure behind "Postgres is expensive", but **it is
not currently being paid.** Postgres runs in local Docker only.

If it were ever deployed, a Burstable `B1ms` (~$15–25/mo) would serve the
current corpus (392 sections) comfortably. The cost is the SKU, not the engine.

## Projected, if the Cosmos cutover completes

Azure AI Search Basic (~$75/mo) is needed for lexical parity, since Cosmos has
no full-text search. That **more than doubles** the current data-layer spend and
offsets most of the notional Postgres saving. Phase 3's eval decides whether it
is worth it.

## Agent model spend

Routing policy in [agents/dispatch-log.md](../agents/dispatch-log.md). Rough
per-call cost ratio: haiku 1x, sonnet ~3x, opus ~15x.

| Work | Model | Was it the right call? |
|---|---|---|
| Live diagnostics, log gathering | haiku | ✅ Both INC-001 agents found the root cause |
| Codebase mapping | sonnet | ✅ Accurate |
| Applying a specified plan | sonnet | ✅ Needed independent verification after |
| Writing tests | sonnet | ✅ |
| Correctness review | opus | ✅ Found bugs sonnet missed in the same files |
| Architecture design | opus | ✅ Found the production data-loss bug |

**The pattern worth keeping:** cheap models are reliable at *gathering* and
*applying*. They are not reliable at *judging*. Both haiku agents on INC-001
correctly found the empty env vars, and both then recommended an endpoint host
that does not exist for that account — a verification step caught it.
