# Deploy instructions — Node/MUI dependency upgrade

**Audience:** GitHub Copilot (or any agent) operating in this repo, `varunreddycs/policy-back`.
**Goal:** commit the pending frontend dependency upgrade, get it reviewed via PR, and deploy it
to `platform.mistrv.com` through the existing `azure-dev` GitHub Actions workflow.

Delete this file once the deploy is confirmed — it's a one-time runbook, not permanent docs.

---

## 0. Context — what this change is and why

The working tree on branch `phase3.1-redesign` has an uncommitted frontend dependency upgrade:

| Package | Before | After |
|---|---|---|
| react, react-dom | 19.2.4 | 19.2.7 |
| react-router-dom | 7.13.1 | 7.18.1 |
| @mui/material, @mui/icons-material | 7.3.8 | **9.2.0** (MUI skipped v8; v9 resyncs with MUI X) |
| @types/react | 19.2.14 | 19.2.17 |
| @types/react-dom | 19.2.14 | 19.2.3 |
| typescript | 5.7.2 | 5.9.3 |
| vite | 6.0.5 | 6.4.3 |

Also changed:
- **`Dockerfile`** — web-build stage base image bumped `node:20-alpine` → `node:22-alpine` (Node 20 is
  being deprecated; 22 is current Active LTS).
- **`apps/web/src/components/EvidenceDrawer.tsx`** — MUI v9 removed `Drawer`'s `PaperProps` prop in
  favor of the slots API. Changed `PaperProps={{ sx: {...} }}` to `slotProps={{ paper: { sx: {...} } }}`.
  This was the only breaking API usage found in the codebase.
- **13 files** under `apps/web/src/` were mechanically rewritten by the official MUI codemod
  (`npx @mui/codemod@latest v9.0.0/system-props src`), converting shorthand style props like
  `color="text.secondary"` into `sx={{ color: "text.secondary" }}`, which MUI v9 requires. These are
  cosmetic/mechanical diffs, not behavior changes.
- Deliberately **held back**: Vite 8 (bundler swap to Rolldown) and TypeScript 7.0 (new Go-native
  compiler) — both are very fresh majors with real migration risk; skip them in this change.

This has already been verified locally:
- `cd apps/web && npm run build` (`tsc -b && vite build`) — passes clean.
- `docker build -t test --target web-build .` — passes clean with the `node:22-alpine` base.
- `npm audit` — 0 vulnerabilities after `npm audit fix` cleared 4 transitive advisories pulled in by
  the dependency bump.
- Vite dev server — all 5 SPA routes (`/`, `/console`, `/audit`, `/ingest`, `/roadmap`) return HTTP 200.
- **Not verified:** actual browser rendering / visual regression check of MUI v9 styling. No browser
  tool was available. Do this manually after deploy, or ask a human to eyeball the console UI.

---

## 1. Preconditions to check before doing anything

```bash
git status --short
git rev-parse --abbrev-ref HEAD
```

Expect: branch `phase3.1-redesign`, with these paths modified/untracked:
```
M  Dockerfile
M  apps/web/package.json
M  apps/web/package-lock.json
M  apps/web/src/App.tsx
M  apps/web/src/components/*.tsx   (multiple)
M  apps/web/src/pages/*.tsx        (multiple)
M  apps/web/tsconfig.app.tsbuildinfo
```

**Do NOT stage or commit these unrelated paths** if present — they are stale build artifacts /
local-only files, not part of this change:
```
apps/api/__pycache__/*.pyc
apps/web/dist/*              (generated build output, rebuilt by CI/Docker — do not hand-commit)
packages/core/__pycache__/*.pyc
packages/rag/__pycache__/*.pyc
packages/ranking/__pycache__/*.pyc
.claude/
Architecture.md              (unrelated doc from a prior task)
tests/swagger_questions/     (unrelated, untracked test fixtures from a prior task)
```

If `apps/web/dist/index.html` shows as modified, leave it out of the commit — the Docker build
regenerates `dist/` from source (`Dockerfile` line: `RUN npm run build`), so a stale local `dist/`
should not be committed.

---

## 2. Stage and commit only the upgrade files

```bash
git add Dockerfile \
  apps/web/package.json apps/web/package-lock.json \
  apps/web/src/App.tsx \
  apps/web/src/components/AnswerCard.tsx \
  apps/web/src/components/AnswerStream.tsx \
  apps/web/src/components/AskForm.tsx \
  apps/web/src/components/CitationsChips.tsx \
  apps/web/src/components/EvidenceDrawer.tsx \
  apps/web/src/components/EvidenceTable.tsx \
  apps/web/src/components/QuickReplyChips.tsx \
  apps/web/src/components/ReferencesPanel.tsx \
  apps/web/src/components/TopBar.tsx \
  apps/web/src/pages/ConsolePage.tsx \
  apps/web/src/pages/IngestPage.tsx \
  apps/web/src/pages/RoadmapPage.tsx

git status --short   # confirm only the list above (+ maybe tsconfig.app.tsbuildinfo) is staged
```

If `apps/web/tsconfig.app.tsbuildinfo` is tracked in this repo (check `git ls-files | grep tsbuildinfo`),
include it too; otherwise leave it (it should probably be gitignored, but that's out of scope here).

Commit:

```bash
git commit -m "$(cat <<'EOF'
chore(web): upgrade React/MUI/Vite deps, MUI v7->v9, Node 20->22 base image

Bumps react/react-dom/react-router-dom to latest patch, MUI to v9.2.0
(v8 does not exist -- MUI resynced with MUI X's version line), and
applies the official v9.0.0/system-props codemod across 13 files.
Fixes the one breaking API usage (Drawer PaperProps -> slotProps).
Bumps the web-build Docker stage base image from node:20-alpine to
node:22-alpine ahead of Node 20 deprecation. Vite 8 and TypeScript 7.0
are deliberately held back pending separate migration work.

Verified: tsc -b && vite build clean; docker build --target web-build
clean on node:22-alpine; npm audit 0 vulnerabilities; all SPA routes
return 200 locally. Not verified: browser visual regression check.
EOF
)"
```

---

## 3. Push and open a PR into `main`

```bash
git push -u origin phase3.1-redesign
```

If `phase3.1-redesign` already has an open/merged PR into `main` (check first — it may already be
merged from earlier work), open a **new** PR for just this change instead of reusing an old one:

```bash
gh pr create \
  --base main \
  --head phase3.1-redesign \
  --title "chore(web): upgrade React/MUI/Vite deps + Node 22 build image" \
  --body "$(cat <<'EOF'
## What
- react/react-dom/react-router-dom -> latest patch
- @mui/material + @mui/icons-material 7.3.8 -> 9.2.0 (v8 skipped by MUI; v9 resyncs with MUI X)
- typescript 5.7.2 -> 5.9.3, vite 6.0.5 -> 6.4.3
- Dockerfile web-build stage: node:20-alpine -> node:22-alpine
- Applied the official `@mui/codemod v9.0.0/system-props` (13 files, mechanical sx-prop rewrites)
- Fixed the one breaking MUI v9 API usage: EvidenceDrawer's `PaperProps` -> `slotProps.paper`

## Deliberately not included
Vite 8 (Rolldown bundler swap) and TypeScript 7.0 -- both very fresh majors, held back to keep
this change's risk scoped to the MUI major bump.

## Verified
- [x] `tsc -b && vite build` clean
- [x] `docker build --target web-build` clean on the new node:22-alpine base
- [x] `npm audit` -- 0 vulnerabilities (fixed 4 transitive advisories surfaced by the bump)
- [x] All SPA routes (`/`, `/console`, `/audit`, `/ingest`, `/roadmap`) return 200 via local Vite dev server
- [ ] Manual browser check of MUI v9 styling/visual regressions -- **do this before or right after merge**

🤖 Generated with GitHub Copilot
EOF
)"
```

---

## 4. Merge and deploy

The deploy pipeline is `.github/workflows/azure-dev.yml` — it triggers automatically `on: push` to
`main`, and can also be triggered manually via `workflow_dispatch`.

1. **Review the PR diff** — confirm nothing outside the file list in step 2 leaked in (especially:
   no `dist/`, no `.pyc`, no unrelated docs).
2. **Merge the PR** (squash or merge commit, per repo convention — check recent merged PRs with
   `gh pr list --state merged --limit 5` if unsure).
3. Merging to `main` auto-triggers the `azure-dev` workflow. Watch it:
   ```bash
   gh run watch --workflow=azure-dev.yml
   ```
   or list recent runs:
   ```bash
   gh run list --workflow=azure-dev.yml --limit 5
   ```
4. If it doesn't auto-trigger (e.g. branch protection delays, or you need to redeploy without a new
   commit), trigger it manually:
   ```bash
   gh workflow run azure-dev.yml --ref main
   ```

**Known-good baseline:** the `azure-dev` workflow last succeeded on `phase3.1-redesign` via manual
`workflow_dispatch` (run completed in ~3m). If this new run fails, diff its error against that
known-good run rather than assuming the dependency upgrade broke deploy — the Docker build for this
exact change was already verified locally in step 0.

---

## 5. Post-deploy verification

Once the workflow reports success:

1. Open `https://platform.mistrv.com/console`, `/audit`, `/ingest`, `/roadmap` in a real browser.
2. Visually confirm: MUI components render with correct spacing/borders (v9's Grid, Drawer, and
   `sx`-prop rewrites are the highest-risk surfaces), no console errors, evidence drawer opens
   correctly with the right width (this is the file with the breaking-API fix — test it explicitly:
   go to `/console`, ask a question, open the evidence drawer).
3. Check the API is still healthy: `GET https://platform.mistrv.com/health` (or whatever the
   `apps/api/routers/health.py` route is) if the deploy also touched the API image — it shouldn't
   have, since this change is frontend/Dockerfile-base-image only, but confirm the API container
   still starts (the Dockerfile's second stage, `python:3.12-slim`, is unchanged).

---

## 6. Cleanup (unrelated housekeeping, do only if asked)

There is a leftover empty branch `hotfix/ci-setup-azd` on `origin` from an earlier, separate,
abandoned attempt to patch `azure-dev.yml` via the GitHub API (it was blocked by an OAuth
`workflow` scope restriction and never got a commit). It's unrelated to this upgrade. If you want
it removed:
```bash
git push origin --delete hotfix/ci-setup-azd
```
Confirm with the repo owner before deleting — don't do this automatically as part of the deploy.
