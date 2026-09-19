"""Load the committed swagger_questions set as eval cases."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# _templates hold REPLACE_WITH_YOUR_QUESTION placeholders, not real questions.
_EXCLUDED_DIRS = frozenset({"_templates"})


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    """One /v1/ask request payload plus the identity used to key its scores."""

    question_id: str
    suite: str
    category: str
    variant: str
    payload: dict[str, Any] = field(compare=False)

    @property
    def question(self) -> str:
        return str(self.payload.get("question", ""))


def _parse_name(path: Path) -> tuple[str, str]:
    """``appeals_deadline__strict.json`` -> ("appeals_deadline", "strict")."""
    stem = path.stem
    topic, _, variant = stem.partition("__")
    return topic, (variant or "default")


def questions_dir() -> Path:
    """Repo-relative location of the committed question set."""
    return Path(__file__).resolve().parents[2] / "tests" / "swagger_questions"


def load_questions(root: Path | None = None) -> list[EvalQuestion]:
    """Load every question payload, sorted by id for stable reporting."""
    base = root or questions_dir()
    if not base.exists():
        raise FileNotFoundError(f"Question set not found at {base}")

    found: list[EvalQuestion] = []
    for path in sorted(base.rglob("*.json")):
        rel = path.relative_to(base)
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue

        payload = json.loads(path.read_text(encoding="utf-8"))
        if not str(payload.get("question", "")).strip():
            continue
        if "REPLACE_WITH_YOUR_QUESTION" in json.dumps(payload):
            continue

        topic, variant = _parse_name(path)
        parts = rel.parts
        suite = parts[0]
        category = parts[1] if len(parts) > 2 else "root"

        found.append(
            EvalQuestion(
                question_id="/".join([*parts[:-1], topic]),
                suite=suite,
                category=category,
                variant=variant,
                payload=payload,
            )
        )

    return found
