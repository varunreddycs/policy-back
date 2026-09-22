"""Run the RAG eval harness against a live /v1/ask endpoint (Q3).

Usage:
    # score the committed question set and compare to the baseline
    uv run python scripts/run_eval.py --base-url http://localhost:8001

    # accept the current numbers as the new baseline (review the diff!)
    uv run python scripts/run_eval.py --base-url http://localhost:8001 --record

Exits non-zero when a metric regresses beyond its tolerance, so CI can gate on
retrieval and prompt changes.

LLM-judged metrics (RAGAS faithfulness / context precision-recall, DeepEval)
are intentionally NOT wired in yet: the committed question set has no reference
answers, and both libraries need a live judge model. Add reference answers to
the question payloads first, then layer them on top of these results.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.eval.baseline import (
    build_report,
    compare,
    load_baseline,
    newly_refused,
    save_baseline,
)
from packages.eval.metrics import aggregate, score_response
from packages.eval.questions import load_questions


def _post_json(
    url: str, payload: dict[str, Any], timeout: int
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the RAG eval harness")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", "http://localhost:8001"),
        help="API base URL (default: $API_BASE_URL or http://localhost:8001)",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Overwrite the committed baseline with this run",
    )
    parser.add_argument(
        "--timeout", type=int, default=60, help="Per-request timeout (s)"
    )
    parser.add_argument(
        "--notes", default=None, help="Note stored with a recorded baseline"
    )
    parser.add_argument(
        "--suite",
        default=None,
        help="Restrict to one corpus (e.g. nist). Baselines are per-suite.",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Also write the full report here"
    )
    args = parser.parse_args()

    ask_url = f"{args.base_url.rstrip('/')}/v1/ask"
    questions = load_questions(suite=args.suite)
    if not questions:
        print("No eval questions found", file=sys.stderr)
        return 2

    print(f"Running {len(questions)} questions against {ask_url}\n")

    results = []
    for q in questions:
        try:
            status, response = _post_json(ask_url, q.payload, args.timeout)
        except OSError as exc:
            print(f"  API unreachable at {args.base_url}: {exc}", file=sys.stderr)
            return 2

        result = score_response(
            question_id=q.question_id,
            suite=q.suite,
            category=q.category,
            variant=q.variant,
            question=q.question,
            status=status,
            response=response,
        )
        results.append(result)

        if status != 200:
            mark = f"ERR {status}"
        elif result.refused:
            mark = f"refused:{result.refusal_code}"
        elif result.is_fallback:
            mark = "fallback"
        else:
            mark = f"ok cites={result.citation_count}"
        print(f"  {q.question_id:<55} {mark}")

    metrics = aggregate(results)
    backend = os.environ.get("RETRIEVER_BACKEND", "unknown")
    report = build_report(
        metrics, results, backend=backend, notes=args.notes, suite=args.suite
    )

    print("\n--- metrics ---")
    for key, value in metrics.to_dict().items():
        print(f"  {key}: {value}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nReport written to {args.out}")

    if args.record:
        path = save_baseline(report, suite=args.suite)
        print(f"\nBaseline recorded at {path}")
        return 0

    baseline = load_baseline(suite=args.suite)
    if baseline is None:
        print("\nNo baseline recorded yet — run with --record to create one.")
        return 0

    regressions = compare(metrics, baseline)
    churned = newly_refused(results, baseline)

    if churned:
        print("\nQuestions that regressed from answered to refused:")
        for qid in churned:
            print(f"  - {qid}")

    if regressions:
        print("\nREGRESSIONS:")
        for reg in regressions:
            print(f"  - {reg.describe()}")
        return 1

    print("\nNo regressions against baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
