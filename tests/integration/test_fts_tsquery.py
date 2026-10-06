"""Q7: verify the generated tsquery against a real PostgreSQL.

The control-ID FTS term is a string handed to ``to_tsquery``, so only Postgres
can confirm it parses and matches. Unit tests can check the shape of the token;
they cannot catch a syntax error.

    RUN_INTEGRATION=1 uv run pytest tests/integration/test_fts_tsquery.py
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from packages.retrieval.control_ids import extract_control_ids


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    # SQLAlchemy needs the driver-qualified form; accept either.
    return url


def _should_run() -> bool:
    return os.environ.get("RUN_INTEGRATION") == "1" and bool(_database_url())


pytestmark = pytest.mark.integration


def _fts_control_tokens(query: str) -> list[str]:
    """Same construction as PgsqlFtsRetriever.retrieve."""
    return sorted({f"'{cid.lower()}'" for cid in extract_control_ids(query)})


@pytest.fixture(scope="module")
def engine():
    if not _should_run():
        pytest.skip("RUN_INTEGRATION!=1 or DATABASE_URL unset")
    eng = create_engine(_database_url() or "", future=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable: {exc}")
    return eng


@pytest.mark.parametrize(
    "query",
    [
        "What does AC-2 require?",
        "IA-5(1) authenticator management",
        "SC-7(3) boundary protection",
        "ac-02 and sc-7(3) together",
    ],
)
def test_control_tokens_parse_as_valid_tsquery(engine, query: str) -> None:
    """A malformed term would raise a syntax error here."""
    tokens = _fts_control_tokens(query)
    assert tokens, f"no control ids extracted from {query!r}"

    or_query = " | ".join(tokens)
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT to_tsquery('english', :q)::text"), {"q": or_query}
        ).scalar_one()

    assert result


def test_bare_enhancement_id_would_be_a_syntax_error(engine) -> None:
    """Documents WHY the token is quoted: unquoted parens are an error."""
    from sqlalchemy.exc import DatabaseError

    with engine.connect() as conn, pytest.raises(DatabaseError):
        conn.execute(
            text("SELECT to_tsquery('english', :q)"), {"q": "ia-5(1) | authent"}
        ).scalar_one()


@pytest.mark.parametrize(
    ("section_text", "query", "expected"),
    [
        ("AC-2 Account Management requires review", "AC-2", True),
        ("IA-5(1) Password Authenticators", "IA-5(1)", True),
        # The control family still matches a query for the bare family id.
        ("IA-5(1) Password Authenticators", "IA-5", True),
        # Critically, AC-2 must NOT match AC-20.
        ("AC-20 Use of External Systems", "AC-2", False),
        ("AC-2 Account Management", "AC-20", False),
    ],
)
def test_control_token_matches_the_right_sections(
    engine, section_text: str, query: str, expected: bool
) -> None:
    tokens = _fts_control_tokens(query)
    assert tokens

    with engine.connect() as conn:
        matched = conn.execute(
            text("SELECT to_tsvector('english', :body) @@ to_tsquery('english', :q)"),
            {"body": section_text, "q": " | ".join(tokens)},
        ).scalar_one()

    assert bool(matched) is expected
