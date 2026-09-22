"""Baseline persistence and regression comparison (Q3).

A committed baseline turns the eval from a report into a gate: a retrieval or
prompt change must either hold the line or land with an explicitly re-recorded
baseline, which shows up in review as a measured delta.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.eval.metrics import EvalMetrics, QuestionResult

# Metrics where a DROP is a regression, with the tolerance allowed before
# failing. Retrieval is not perfectly deterministic across runs, so each has a
# small band; anything outside it is a real movement worth a human decision.
_HIGHER_IS_BETTER: dict[str, float] = {
    "answer_rate": 0.05,
    "citation_coverage": 0.05,
    "grounded_citation_rate": 0.05,
    "mean_confidence": 0.05,
}

# Metrics where a RISE is a regression.
_LOWER_IS_BETTER: dict[str, float] = {
    "refusal_rate": 0.05,
    "fallback_rate": 0.05,
    "errors": 0.0,
}


@dataclass(frozen=True, slots=True)
class Regression:
    metric: str
    baseline: float
    current: float
    delta: float
    tolerance: float

    def describe(self) -> str:
        direction = "dropped" if self.delta < 0 else "rose"
        return (
            f"{self.metric} {direction} from {self.baseline} to {self.current} "
            f"(delta {self.delta:+.4f}, tolerance {self.tolerance})"
        )


def baseline_path(suite: str | None = None) -> Path:
    """Baselines are per-corpus: a NIST run must not be compared to an Ohio one."""
    name = f"baseline_{suite}.json" if suite else "baseline.json"
    return Path(__file__).resolve().parents[2] / "tests" / "eval" / name


def build_report(
    metrics: EvalMetrics,
    results: list[QuestionResult],
    *,
    backend: str,
    notes: str | None = None,
    suite: str | None = None,
) -> dict[str, Any]:
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "retriever_backend": backend,
        "suite": suite,
        "notes": notes,
        "metrics": metrics.to_dict(),
        "questions": {r.question_id: r.to_dict() for r in results},
    }


def save_baseline(
    report: dict[str, Any], path: Path | None = None, *, suite: str | None = None
) -> Path:
    target = path or baseline_path(suite)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def load_baseline(
    path: Path | None = None, *, suite: str | None = None
) -> dict[str, Any] | None:
    target = path or baseline_path(suite)
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def compare(
    current: EvalMetrics,
    baseline: dict[str, Any],
) -> list[Regression]:
    """Return every metric that moved the wrong way beyond its tolerance."""
    prior = baseline.get("metrics") or {}
    regressions: list[Regression] = []

    for metric, tolerance in _HIGHER_IS_BETTER.items():
        if metric not in prior:
            continue
        before = float(prior[metric])
        now = float(getattr(current, metric))
        if now < before - tolerance:
            regressions.append(Regression(metric, before, now, now - before, tolerance))

    for metric, tolerance in _LOWER_IS_BETTER.items():
        if metric not in prior:
            continue
        before = float(prior[metric])
        now = float(getattr(current, metric))
        if now > before + tolerance:
            regressions.append(Regression(metric, before, now, now - before, tolerance))

    return regressions


def newly_refused(results: list[QuestionResult], baseline: dict[str, Any]) -> list[str]:
    """Questions that used to be answered and now refuse.

    Aggregate rates can stay flat while the *set* of answered questions churns;
    this attributes the change to specific questions.
    """
    prior = baseline.get("questions") or {}
    changed: list[str] = []
    for r in results:
        before = prior.get(r.question_id)
        if not isinstance(before, dict):
            continue
        if before.get("answered") and not r.answered:
            changed.append(r.question_id)
    return sorted(changed)
