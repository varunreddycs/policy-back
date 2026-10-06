# Reports

Finished analysis worth keeping. One file per piece of work, newest first.

Reports here are **conclusions with evidence attached** — not transcripts. If a
claim has no command output, commit SHA, or `file:line` behind it, it does not
belong here.

| Date | Report | Source |
|---|---|---|
| 2026-10-05 | [INC-001 root cause](../incidents/001-platform-insufficient-evidence.md) | 2× haiku diagnostics + direct verification |
| 2026-09-24 | [Cosmos cutover plan](../milestones/02-cosmos-cutover.md) | 3× sonnet explore + 1× opus design |
| 2026-09-24 | [S5 sectioning](../milestones/01-s5-sectioning.md) | opus review + sonnet execute/test |

## Standing lesson

Every agent report in this project has been independently re-checked before
being acted on, and that check has caught something real more than once:

- Both INC-001 agents correctly found the empty env vars, then both recommended
  `mythri-resource.openai.azure.com`. That host does not exist for this account
  — it is an **AIServices** resource on `cognitiveservices.azure.com`. Applying
  the recommendation verbatim would have left the outage in place.
- An explorer reported `azure-cosmos` missing from `requirements.txt`; it is
  present at line 13 and was merely absent from the local `.venv`.
- A sonnet executor reported all fixes applied; true, but its later edits
  introduced two new bugs that only newly written tests caught.

Agents are good at finding and gathering. Verify before acting.
