# Agent dispatch log

Which agent ran, on which model, what it was asked, and whether its output held
up. Newest first.

**Routing policy** (cost control): cheap models for mechanical work — searching,
tracing, applying a specified plan, gathering diagnostics. Expensive models only
for judgment — correctness review, architecture, root-cause analysis.

| Model | Use for |
|---|---|
| `haiku` | Log gathering, probing, file location, verbatim reporting |
| `sonnet` | Codebase mapping, applying an approved plan, writing tests |
| `opus` | Correctness review, architecture design, root-cause reasoning |

---

## 2026-10-06 — S3 crosswalk recon

| Agent | Model | Task | Outcome |
|---|---|---|---|
| Explore | sonnet | Map reference schema/pipeline, CitationItem, why Cosmos refs=0 | ✅ Found the seed bypasses the worker and the references router 500s in prod — both verified |
| researcher | sonnet | Find official NIST CSF↔800-53 crosswalk data + STRM vocabulary | 🟡 Useful leads, but the key fact was UNCONFIRMED; fetching the file showed it is XLSX and untyped |
| executor | sonnet | Port references router + Cosmos hydration (INC-002) | ✅ Clean; live Cosmos check confirmed the new query is valid SQL, which fakes could not |
| executor | sonnet | Implement half B (control citations) to a written spec | ✅ Built to spec, 302 pass. Review then caught a non-NIST mislabel path (HR-4) the spec itself missed — fixed |

## 2026-10-05 — INC-001 platform.mistrv.com

| Agent | Model | Task | Outcome |
|---|---|---|---|
| general-purpose | haiku | Probe API endpoints, find base URL, check replicas | see [incidents/001](../incidents/001-platform-insufficient-evidence.md) |
| general-purpose | haiku | Pull container app logs + env config | see [incidents/001](../incidents/001-platform-insufficient-evidence.md) |

## 2026-09-24 — Cosmos cutover planning

| Agent | Model | Task | Outcome |
|---|---|---|---|
| Explore | sonnet | Map Cosmos repo layer vs Postgres parity | ✅ Found interface parity complete, gaps behavioral not missing-method |
| Explore | sonnet | Inventory Postgres-specific coupling | ✅ Found `IngestionService` has no Cosmos path at all — the key finding |
| Explore | sonnet | Locate migrator repo + Azure config | ✅ Found migrator omits vector index policy |
| Plan | opus | Design `IngestionService` port | ✅ **Found the production data-loss bug.** Highest-value dispatch so far |

**Note:** the opus Plan agent found a live data-loss bug that three sonnet
explorers had looked at the same file and missed. Evidence that the cheap/
expensive split should follow *judgment required*, not *file count*.

## 2026-09-24 — S5 sectioning

| Agent | Model | Task | Outcome |
|---|---|---|---|
| code-reviewer | opus | Review inherited sectioner code | ✅ Found 8 defects incl. phantom-section corruption; all reproduced |
| explorer | sonnet | Map S5 integration surface | ✅ Accurate; found metadata is dropped by the worker |
| executor | sonnet | Apply the 10 specified fixes | ✅ All verified independently afterward |
| test-writer | sonnet | Write 58 regression tests | ✅ Mutation-verified; self-corrected one bad assertion |

**Note:** the opus review caught the phantom-section bug — a cheaper model would
plausibly have wired the inherited code as written.

---

## Verification discipline

Every agent result above was independently re-checked before being acted on.
Two cases where that mattered:

- A sonnet executor reported "all 10 defects fixed"; re-running the cases
  confirmed it, but the same session's later edits introduced two new bugs that
  only the new tests caught.
- An explorer reported `azure-cosmos` missing from `requirements.txt`; direct
  grep showed it present at line 13 and merely absent from the local `.venv`.

Treat agent reports as evidence to check, not conclusions to adopt.
