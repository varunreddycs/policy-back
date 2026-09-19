"""RAG evaluation harness (Q3).

Scores the committed swagger_questions set against a live ``/v1/ask`` response
and compares the result to a committed baseline, so a change to
RETRIEVER_BACKEND, fusion weights, the refusal threshold or the strict-citation
prompt cannot ship without a measured delta.
"""

from packages.eval.metrics import (
    EvalMetrics,
    QuestionResult,
    aggregate,
    score_response,
)
from packages.eval.questions import EvalQuestion, load_questions

__all__ = [
    "EvalMetrics",
    "EvalQuestion",
    "QuestionResult",
    "aggregate",
    "load_questions",
    "score_response",
]
