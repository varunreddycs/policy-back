# .project — work tracking

Durable state for multi-session, multi-agent work. Everything here is committed
so any agent or session can pick up where the last one stopped.

| Folder | Holds |
|---|---|
| `milestones/` | One file per milestone. Scope, decisions, status, commits. |
| `agents/` | Agent dispatch log: who ran, which model, what they returned. |
| `reports/` | Finished analysis handed back by agents or sessions. |
| `metrics/` | Test counts, eval scores, cost figures — numbers over time. |
| `incidents/` | Outages and production defects, newest first. |
| `archive/` | Parked work. Still true, just not active. |

## Conventions

- **Filenames**: `NN-short-slug.md`, numbered so they sort in work order.
- **Status vocabulary**: `planned` → `active` → `blocked` → `done` → `parked`.
- **Every claim carries evidence.** A commit SHA, a command and its output, or a
  `file:line`. Assertions without evidence are the thing this folder exists to
  prevent.
- **Record what was verified vs. what was inferred.** They are not the same and
  the distinction is what makes these files worth reading later.
- **Costs**: note which model did the work, so the cheap/expensive split stays
  visible and reviewable.

## Current state

See `milestones/00-INDEX.md` for what is active right now.
