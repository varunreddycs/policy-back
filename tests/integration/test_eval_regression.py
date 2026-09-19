"""Q3: eval regression gate against a live /v1/ask endpoint.

Runs the committed question set and fails if any metric moved the wrong way
past its tolerance versus tests/eval/baseline.json.

    RUN_EVAL=1 API_BASE_URL=http://localhost:8001 uv run pytest tests/integration/test_eval_regression.py

Re-record the baseline deliberately (and review the diff) with:

    uv run python scripts/run_eval.py --base-url http://localhost:8001 --record
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import pytest

from packages.eval.baseline import compare, load_baseline, newly_refused
from packages.eval.metrics import aggregate, score_response
from packages.eval.questions import load_questions


def _should_run() -> bool:
    return os.environ.get("RUN_EVAL") == "1"


def _post_json(
    url: str, payload: dict[str, Any], timeout: int = 60
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return int(getattr(resp, "status", 200)), (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return int(exc.code), (json.loads(raw) if raw else {})
        except ValueError:
            return int(exc.code), {"raw": raw}


@pytest.mark.integration
def test_eval_set_has_no_regression_against_baseline() -> None:
    if not _should_run():
        pytest.skip("RUN_EVAL!=1")

    baseline = load_baseline()
    if baseline is None:
        pytest.skip("No baseline recorded — run scripts/run_eval.py --record first")

    base_url = os.environ.get("API_BASE_URL", "http://localhost:8001").rstrip("/")
    ask_url = f"{base_url}/v1/ask"

    questions = load_questions()
    assert questions, "No eval questions found"

    results = []
    for q in questions:
        try:
            status, response = _post_json(ask_url, q.payload)
        except OSError as exc:
            pytest.skip(f"API not reachable at {base_url}: {exc}")

        results.append(
            score_response(
                question_id=q.question_id,
                suite=q.suite,
                category=q.category,
                variant=q.variant,
                question=q.question,
                status=status,
                response=response,
            )
        )

    metrics = aggregate(results)
    regressions = compare(metrics, baseline)
    churned = newly_refused(results, baseline)

    detail = {
        "regressions": [r.describe() for r in regressions],
        "newly_refused": churned,
        "current": metrics.to_dict(),
        "baseline": baseline.get("metrics"),
    }
    assert not regressions, detail
