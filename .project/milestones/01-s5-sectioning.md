# 01 — S5 structure-aware sectioning (#16)

**Status: done.** Commits `953dd1d`, `6e64c79` on
`feat/s5-structure-aware-sectioning`. Not pushed.

## Scope

In: heading-aware sectioning, DOCX auto-numbering, migration 008 for a
`needs_review` parse status.
Out (→ issue #39): DOCX tables, headers/footers, PDF heading recovery.
Policy: new ingests only — existing rows keep their `chunk-N` paths.

**S3 was deliberately skipped.** Issue #16 states S5 is its prerequisite;
building the OSCAL crosswalk on `chunk-N` paths would have built it on a broken
data model.

## The payoff, measured

```
ref   | structured paths | old chunk paths
3.2   | resolved         | UNRESOLVED
AC-2  | resolved         | UNRESOLVED
```

Dotted and control references cannot resolve **at all** against `chunk-N`. This
confirms #16's claim that the low reference-resolution rate was a data-model
disconnect, not a tuning problem. Side effect: Q7's control-ID boost could never
fire before, because `_candidate_ids` only ever saw `"Chunk 3"`.

## Defects fixed in the inherited draft

The code existed but was unwired, untested, and had 10 defects — all reproduced
by running it, not inferred. The two that mattered:

1. **DOCX style `"Heading 1"` (with a space) never matched.** Word, LibreOffice
   and Google Docs all emit that form, so every heading in those files was
   dropped and the feature silently did nothing.
2. **Inline cross-references became phantom sections.** `"Section 5 of the Ohio
   Revised Code applies"` created a fake section that truncated the real section
   above it, and `reference_resolver` then resolved genuine references to the
   fragment — confident-but-wrong resolutions, worse than the status quo.

Also: `.title()` cited "HIPAA COMPLIANCE" as "Hipaa Compliance"; `#p2`/`~2`
suffixes polluted `section_path` and made the resolver order-dependent.

## Constraint discovered

`needs_review` had to stay confined to `policy_versions` — `ingest_items` and
`ingest_batches` carry their own CHECK constraints admitting only
received/queued/processing/completed/failed. Those map to `failed`.

## Verification

58 new tests, mutation-verified (re-introducing two bugs failed 5 and 3 tests
respectively). Suite 216 → 274.
