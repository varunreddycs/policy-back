# Milestone index

Last updated: 2026-10-05

| # | Milestone | Status | Detail |
|---|---|---|---|
| — | INC-001 platform.mistrv.com degraded | ✅ resolved 2026-10-05 | [incidents/001](../incidents/001-platform-insufficient-evidence.md) |
| 01 | S5 structure-aware sectioning | ✅ done | [01](01-s5-sectioning.md) |
| 02 | Cosmos cutover — Phase 0 | ✅ done | [02](02-cosmos-cutover.md) |
| 02 | Cosmos cutover — Phases 1–6 | ⏸️ **parked** | [02](02-cosmos-cutover.md) |
| 03 | S3 OSCAL crosswalk (#14) | 📋 planned | unblocked by S5 |
| 04 | S4, S6, S7 (#15, #17, #18) | 📋 planned | GitHub milestone "02 Strategic bets" |
| 05 | S5b parser scope (#39) | 📋 planned | DOCX tables, headers/footers, PDF headings |

## Ordering

GitHub milestones on `varunreddycs/policy-back` are the work queue, tracked by
epic #31. Take the lowest open issue in the earliest milestone with open issues.

1. `00 Fix-first` (#2–#4) — closed, merged to main
2. `01 Quick wins` (#5–#11) — Q1–Q7 all committed
3. `02 Strategic bets` (#12–#18) — S1, S2, S5 done; S3 next
4. `03 Table-stakes` (#19–#26)
5. `04 Moonshots` (#27–#30)

## Branch stack

Each story is a branch stacked on the previous one. None pushed yet.

```
main
 └─ 3.1-redesign-latet-commit
     └─ feat/q1..q7 (PR #38)
         └─ feat/s1-groundedness-verification   cfa5cd3
             └─ feat/s2-as-of-answers           259a136
                 └─ feat/s5-structure-aware-sectioning
                      953dd1d  needs_review
                      6e64c79  sectioning
                      fb84986  cosmos ETag fix
```
