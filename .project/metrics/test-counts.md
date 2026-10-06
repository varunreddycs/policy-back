# Test counts over time

`PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/unit -q -p no:cacheprovider`

| Date | Count | Change | Driver |
|---|---|---|---|
| 2026-10-06 | **317** | +11 | INC-002 references router + versions fix |
| 2026-10-06 | 306 | +23 | S3 control citations |
| 2026-10-05 | **283** | +9 | Cosmos repo tests (first ever direct coverage) |
| 2026-09-24 | 274 | +58 | S5 sectioner + DOCX parser tests |
| 2026-09-24 | 216 | +1 | zero-text → `needs_review` worker test |
| 2026-09-24 | 215 | — | baseline at session start |
| (Phase 2.7) | 25 | — | figure still quoted in `.claude/CLAUDE.md` — **stale by ~258** |

## Coverage gaps

| Area | State |
|---|---|
| `packages/extraction/` | ✅ 58 tests, mutation-verified |
| Cosmos repositories | 🟡 9 tests; CRUD paths covered, SDK/container factory not |
| `cosmos_client_factory.py` | ❌ none |
| `IngestionService` | ❌ none |
| Integration vs. real Cosmos | ❌ none — no emulator in compose |

## Note on mutation testing

Both S5 and the Cosmos ETag fix were mutation-verified: a known bug was
re-introduced and the suite was confirmed to fail, then restored. A passing test
that cannot fail is worth nothing, and two suites here were checked that way
rather than assumed.
