# Milestone index

Last updated: 2026-10-07

| # | Milestone | Status | Detail |
|---|---|---|---|
| — | INC-002 three read endpoints 500 in prod | ✅ deployed 2026-10-06 (PR #41) | [incidents/002](../incidents/002-read-endpoints-500.md) |
| — | INC-001 platform.mistrv.com degraded | ✅ resolved 2026-10-05 | [incidents/001](../incidents/001-platform-insufficient-evidence.md) |
| 01 | S5 structure-aware sectioning | ✅ done | [01](01-s5-sectioning.md) |
| 02 | Cosmos cutover — Phase 0 | ✅ done | [02](02-cosmos-cutover.md) |
| 02 | Cosmos cutover — Phases 1–6 | ⏸️ **parked** | [02](02-cosmos-cutover.md) |
| 03 | S3 half B — control citations | ✅ deployed (PR #40 → #41) | [03](03-s3-crosswalk.md) |
| 03 | S3 half A — CSF 2.0 + crosswalk data | ✅ deployed + loaded (PR #43) |
| 03 | S3 close-out — mapped controls on /ask citations | 🔨 in progress | [03](03-s3-crosswalk.md) |
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

## Deploying

`azure-dev.yml` deploys **only on push to `main`**. Branch from `main`, PR into
`main`; the merge deploys (`azd provision` then `azd deploy`, PR #42). The old
`3.1-redesign-latet-commit` stack was promoted to `main` via PR #41 after it had
drifted (main carried F1/F2/F3 security fixes it lacked).

| PR | Content | State |
|---|---|---|
| #40 | S1, S2, S5, S3-B, Cosmos ETag fix, INC-002 | merged into 3.1 branch |
| #41 | 3.1 branch synced with main → main | merged, deploy failed (azd) |
| #42 | CI: provision before package | merged, deployed 2026-10-06 |
| #43 | S3-A: CSF 2.0 + crosswalk, CSF-id mislabel fix | merged, deployed 2026-10-07 |
