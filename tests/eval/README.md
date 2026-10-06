# RAG eval regression harness (Q3)

Scores the committed `tests/swagger_questions` set against a live `/v1/ask`
and fails when retrieval or answer quality regresses.

## Recording the first baseline

`baseline.json` is **not** committed yet — it has to be generated against a real
stack with the corpus loaded, so that the numbers mean something.

```bash
docker compose up -d --build api worker
uv run alembic upgrade head
# load the corpus, then:
uv run python scripts/run_eval.py --base-url http://localhost:8001 --record
git add tests/eval/baseline.json
```

Commit the baseline. From then on it is the line a change has to hold.

## Running the gate

```bash
# standalone, prints metrics and exits non-zero on regression
uv run python scripts/run_eval.py --base-url http://localhost:8001

# as a test
RUN_EVAL=1 API_BASE_URL=http://localhost:8001 uv run pytest tests/integration/test_eval_regression.py
```

Both skip cleanly when the API is unreachable or no baseline exists, so they
never block the normal unit-test run.

## What is measured

Deterministic, reference-free signals — no LLM judge, so this is safe for CI:

| Metric | Direction | Tolerance | Catches |
|---|---|---|---|
| `answer_rate` | higher better | 0.05 | retrieval got worse; threshold too strict |
| `refusal_rate` | lower better | 0.05 | refusal gate mis-calibrated |
| `citation_coverage` | higher better | 0.05 | answers shipping without citations |
| `grounded_citation_rate` | higher better | 0.05 | prompt edit dropped the citation format |
| `mean_confidence` | higher better | 0.05 | fusion/scoring change |
| `fallback_rate` | lower better | 0.05 | LLM degradation (see Q2) |
| `errors` | lower better | 0.0 | any non-200 |

`newly_refused` additionally names the specific questions that flipped from
answered to refused, since aggregate rates can stay flat while the underlying
set churns.

Per-question scores are persisted in the baseline, so a regression can be
attributed to a question rather than just a number.

## Why not RAGAS / DeepEval yet

Both are LLM-judged and need reference answers. The 25 committed questions are
request payloads only — no expected answer, no expected citations — so
faithfulness and context precision/recall have nothing to score against, and a
live judge model cannot gate CI anyway.

To add them: put `expected_answer` and `expected_citations` on the question
payloads, then layer the judged metrics on top of `QuestionResult`. The harness
keeps the raw response, so nothing here needs to change.

## Re-recording after an intentional change

If a change legitimately moves the numbers, re-record and let the baseline diff
carry the justification into review:

```bash
uv run python scripts/run_eval.py --base-url http://localhost:8001 --record \
  --notes "RRF fusion (Q5): answer_rate +0.08, mean_confidence recalibrated"
```
