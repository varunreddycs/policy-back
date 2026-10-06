# 03 — S3 OSCAL-typed crosswalk graph + control_id citations (#14)

**Status: recon.** Started 2026-10-06. Depends on S5 (done).

## Scope, as written in the issue

- **A — Typed crosswalk.** Add `relationship_type` (equal / subset_of /
  superset_of / intersects / not_applicable, per NIST IR 8477 STRM) and a
  `strength` to references, seeded from the official NIST CSF 2.0 ↔ 800-53
  Rev 5 OLIR mapping.
- **B — Control citations.** First-class `control_id` / `control_name` on
  `CitationItem`; lift the NIST control-ID regex into shared extraction so
  answers say "per AC-2(3)" and can name the mapped CSF/ISO control.

## Known before starting

- Production runs Cosmos. The live `references` container holds **0 documents**
  while `sections` holds 1014 — so the reference pipeline either never runs on
  the Cosmos path or fails silently. That must be understood before a crosswalk
  is built on top of it.
- `packages/retrieval/control_ids.py` already exists (Q7) with control-ID
  extraction and normalization. Half B should extend it, not duplicate it.
- S5 made `section_path` carry real control IDs (`AC-2`, `AC-2(3)`), so citation
  `control_id` can come from structure rather than regex alone.

## Recon in flight

| Agent | Model | Question |
|---|---|---|
| Explore | sonnet | Reference schema, pipeline, citation construction, why Cosmos refs = 0 |
| researcher | sonnet | Official NIST crosswalk files, format, STRM vocabulary, licensing |

## Finding 1 — the NIST data is untyped (verified 2026-10-06)

The issue says to seed `relationship_type` "from the official NIST CSF 2.0 ↔
800-53 Rev 5 OLIR crosswalk". **The file NIST actually serves has no
relationship types.**

Fetched `https://csrc.nist.gov/extensions/nudp/services/json/csf/download?olirids=all`
— despite the URL it returns an **XLSX** (CSF 2.0 Reference Tool export, marked
Final). Parsed the `CSF 2.0` sheet:

| Measure | Value |
|---|---|
| CSF subcategories carrying references | 106 |
| CSF → 800-53 Rev 5.2.0 distinct pairs | **737** |
| CSF → ISO/IEC 27001 distinct pairs | 388 (IDs like `5.24`, `8.15`) |
| Distinct 800-53 controls referenced | 210 |
| STRM words (subset/superset/intersects/equal) anywhere | **none** |

Each reference is a bare line such as `SP 800-53 Rev 5.2.0: PM-11` — an
"informative reference", i.e. "related", with no direction or strength. Rev
5.1.1 and 5.2.0 are both listed, so raw counts double; dedupe on one revision.

NIST IR 8477 STRM types (equal / subset of / superset of / intersects with /
not related to) exist as a vocabulary, and OLIR submissions are *supposed* to
carry them, but no typed CSF↔800-53 file was located at a confirmed URL. The
"strength 0–10, equal=10 / subset=7 / intersects=4" scale circulating online is
a third-party heuristic, not NIST text.

**Consequence for scope:** a v1 seeded from public NIST data can honestly say
*"CSF PR.AA-01 is mapped to AC-2"* but **cannot** say *subset_of* vs
*intersects*. Writing a typed relationship we don't have would fabricate audit
claims in a compliance product. Options: store the relationship as
`related` / `null` with provenance and add types when a typed source is
obtained; or type them by hand/LLM-assisted review, flagged as non-authoritative.

Source handling: NIST content is US public domain; attribute per NIST FAQ.
ISO: store **IDs only**, never ISO control text (copyrighted).

## Finding 2 — why Cosmos `references` = 0 (verified 2026-10-06)

Not a silent failure. **The reference step was never invoked for the corpus.**
All 1014 sections came from `tools/seed_nist_800_53.py`, which writes only
`policies`, `sections` and `embeddings` (`:287-289`) and bypasses the worker.
References are produced only at the end of a worker-processed upload.

Even if it had run, the extractor has **no NIST control-ID pattern** — it finds
§-sections, "see X Policy", URLs and CFR/USC. Over 800-53 text it would find
almost nothing.

## Finding 3 — references API is broken on production (verified)

`apps/api/routers/references.py:33,76` depend on `get_db` (a SQLAlchemy session,
`None` under Cosmos) and call module-level Postgres helpers. Live:

```
GET /v1/policy-sections/{id}/references → 500
```

Same class of defect as the ingestion path in INC-001: a router never ported to
`RepositorySet`. Any crosswalk served through this router would 500 in prod.

## Other facts that shape the design

- `CitationItem` is built in exactly one place: `packages/rag/answer_service.py:696-708`.
  Adding optional `control_id`/`control_name` is additive; `ask.py` and the TS
  `CitationItem` need no breaking change.
- `control_ids.py` lives in `packages/retrieval/` and imports `EvidenceCandidate`;
  extraction importing it would invert layering. Two more copies of the
  control-ID regex exist: `packages/eval/metrics.py:28` (case-sensitive) and
  `packages/grounding/lexical_scorer.py:28`.
- `_candidate_ids` already reads a `control_id` metadata key that no provider writes.
- Cosmos citations always have `version_label=None` (provider never sets it).
- Seeded sections carry the canonical control ID in `section_path` (OSCAL label)
  and the control name in `title`; section ids are deterministic uuid5.
- CSF 2.0 is not in the corpus at all, so CSF-side crosswalk targets must be
  external labels until CSF is seeded.
- `reference_type` CHECK admits only internal_section/cross_policy/external_authority.
- `PolicyReferenceItem` is `extra="forbid"` — new DTO fields must be added there.

## Decisions (user, 2026-10-06)

1. **This pass = half B only (control citations).** Crosswalk data is the next pass.
2. **Crosswalk relationships will be stored untyped** (`related`) with source and
   revision provenance; `relationship_type` / `strength` nullable until a typed
   source exists. No invented STRM types.

Branch: `feat/s3-control-citations` (stacked on `8003480`).

## Half B design

- New `packages/core/control_ids.py` owns the canonical regex plus
  `extract_control_ids`, `normalize_control_ids` (moved verbatim) and new
  `primary_control_id`, `strip_control_prefix`. `packages/retrieval/control_ids.py`
  re-exports them, so existing importers don't change. This fixes the layering
  problem: extraction code can depend on core without pulling in retrieval DTOs.
- `CitationItem` gains optional `control_id`, `control_name`.
- **`control_id` comes only from `section_path` or explicit `control_id` metadata,
  never from the title or body.** A section titled "Implementing AC-2" under
  path 4.1 is not control AC-2, and mislabeling a citation's control is worse
  than leaving it blank.
- `control_name` = title with the leading control ID stripped, so S5's
  "AC-2 Account Management" and the seed's bare "Account Management" agree.
- UI chip shows `AC-2(3) Disable Accounts` when a control is present.

## Deliberately not done

- `packages/eval/metrics.py:28` and `packages/grounding/lexical_scorer.py:28`
  keep their own control-ID regexes. Swapping in the shared normalizer would
  change semantics, not just tidy code: metrics reports raw IDs (would shift
  the recorded eval baseline), and the groundedness scorer compares lowercased
  *raw* text (normalizing "AC-02"→"AC-2" would make it miss zero-padded IDs in
  the source). Follow-up, with the eval re-baselined deliberately.

## Next pass (crosswalk) — blockers to clear first

- `apps/api/routers/references.py` returns **500 in production** (Finding 3);
  must move onto `RepositorySet` before any crosswalk is served through it.
- Seed loader for the 737 CSF→800-53 Rev 5.2.0 + 388 CSF→ISO pairs. CSF is not
  in the corpus, so CSF-side targets start as external labels.

## Half B — implemented and verified (2026-10-06)

Executor (sonnet) built it to spec; review (this session) found and fixed two
things before commit:

1. **Same-shape codes would be labelled as NIST controls.** The regex accepts any
   `XX-n`, so a non-NIST document whose S5 heading is `HR-4 Leave of Absence`
   would have cited `control_id="HR-4"` — the exact mislabeling the no-fallback
   rule exists to prevent. Added `NIST_800_53_FAMILIES` (the 20 Rev 5 families,
   incl. PT and SR which are new in Rev 5) and `is_nist_control_id`.
2. Three copies of the canonical-format f-string inside the new core module →
   one `_canonical`.

Verified against **live production Cosmos metadata**, not fixtures:

```
AC-2      -> AC-2     Account Management
AC-2(3)   -> AC-2(3)  Disable Accounts
IA-5(1)   -> IA-5(1)  Password-based Authentication
PT-2      -> PT-2     Authority to Process Personally Identifiable Information
SC-7      -> SC-7     Boundary Protection
SR-3      -> SR-3     Supply Chain Controls and Processes
```

Suite: 283 → **306**. Frontend `tsc --noEmit` clean.

**Not deployed.** Production still runs the 2026-08-19 image plus the INC-001
env fix; these citation fields reach users only after the next build + deploy.
