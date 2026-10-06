from __future__ import annotations

import re
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from packages.core.dtos import EvidenceCandidate
from packages.db.models.policy_models import (
    ParseStatus,
    Policy,
    PolicySection,
    PolicyVersion,
)
from packages.retrieval.base import IVectorRetriever
from packages.retrieval.control_ids import extract_control_ids


class PgsqlFtsRetriever(IVectorRetriever):
    """PostgreSQL full-text search retriever (Phase 2 scaffold)."""

    def __init__(self, *, session: Session, default_top_k: int | None = None) -> None:
        self._session = session
        self._default_top_k = max(1, int(default_top_k or 40))

    def retrieve(
        self,
        *,
        tenant_id: UUID,
        query: str,
        scope=None,
        user=None,
        top_k: int = 10,
    ) -> list[EvidenceCandidate]:
        q = (query or "").strip()
        if not q:
            return []

        only_current = True
        policy_ids = None
        policy_types = None
        as_of = None
        if scope is not None:
            only_current = bool(getattr(scope, "only_current", True))
            policy_ids = getattr(scope, "policy_ids", None)
            policy_types = getattr(scope, "policy_types", None)
            as_of = getattr(scope, "as_of", None)

        user_department = (
            getattr(user, "department", None) if user is not None else None
        )

        # NOTE: This uses PostgreSQL FTS functions; it will only work against Postgres.
        tsv = func.to_tsvector("english", func.coalesce(PolicySection.text, ""))
        and_tsquery = func.plainto_tsquery("english", q)

        # Fallback: plainto_tsquery ANDs tokens (e.g., 'deadlin' & 'file' & 'appeal'),
        # which can be too strict for natural-language questions. If AND yields no rows,
        # try an OR query built from tokens.
        # Q7: the >= 3 filter silently discarded the very codes compliance users
        # search by — "AC-2" tokenizes to "ac" + "2", both shorter than 3 — so
        # control IDs are extracted first and always kept.
        _control_ids = extract_control_ids(q)
        # to_tsquery treats an unquoted '(' as a grouping operator, so a bare
        # "ia-5(1)" is a syntax error; quoting makes it a valid phrase term.
        # Verified against PG16: '''ia-5(1)''' lexes to 'ia' <-> '-5' <-> '1' and
        # matches a section titled "IA-5(1) ...", while '''ac-2''' matches
        # "AC-2 ..." without also matching "AC-20 ...". See
        # tests/integration/test_fts_tsquery.py for the live check.
        _control_tokens = sorted({f"'{cid.lower()}'" for cid in _control_ids})
        _control_words = {
            part.lower()
            for cid in _control_ids
            for part in re.findall(r"[A-Za-z0-9]+", cid)
        }
        _words = [
            t.lower()
            for t in re.findall(r"[A-Za-z0-9]+", q)
            if len(t) >= 3 and t.lower() not in _control_words
        ]
        _tokens = _control_tokens + _words
        _tokens = _tokens[:8]
        or_tsquery = None
        if len(_tokens) >= 2:
            or_query_str = " | ".join(_tokens)
            or_tsquery = func.to_tsquery("english", or_query_str)

        # S2: as-of answers. A version is authoritative on the requested date when
        # it is the latest READY version of its policy effective on or before it.
        # There is no superseded_at column; supersession is derived from the next
        # version's effective date (falling back to created_at for undated rows),
        # with version_number breaking same-day ties. as_of REPLACES is_current —
        # they are two different definitions of "the" version.
        if as_of is not None:
            _newer = aliased(PolicyVersion)
            _eff = func.coalesce(
                PolicyVersion.effective_date, sa.cast(PolicyVersion.created_at, sa.Date)
            )
            _newer_eff = func.coalesce(
                _newer.effective_date, sa.cast(_newer.created_at, sa.Date)
            )
            version_predicate = sa.and_(
                _eff <= as_of,
                ~sa.exists().where(
                    sa.and_(
                        _newer.policy_id == PolicyVersion.policy_id,
                        _newer.parse_status == ParseStatus.READY.value,
                        _newer_eff <= as_of,
                        sa.or_(
                            _newer_eff > _eff,
                            sa.and_(
                                _newer_eff == _eff,
                                _newer.version_number > PolicyVersion.version_number,
                            ),
                        ),
                    )
                ),
            )
        elif only_current:
            version_predicate = PolicyVersion.is_current.is_(True)
        else:
            version_predicate = sa.true()

        limit_value = max(1, int(top_k or self._default_top_k))

        def _build_stmt(tsquery):
            rank = func.ts_rank(tsv, tsquery)
            public_url = func.coalesce(
                PolicyVersion.metadata_json.op("->>")("source_url"),
                PolicyVersion.metadata_json.op("->>")("public_url"),
                PolicyVersion.metadata_json.op("->>")("url"),
            )
            stmt = (
                select(
                    Policy.id.label("policy_id"),
                    Policy.name.label("policy_name"),
                    PolicyVersion.policy_id,
                    PolicySection.policy_version_id,
                    PolicySection.id,
                    PolicySection.text,
                    PolicySection.section_path,
                    PolicySection.title,
                    PolicySection.section_index,
                    PolicyVersion.is_current,
                    PolicyVersion.version_label,
                    PolicyVersion.effective_date,
                    public_url.label("public_url"),
                    PolicyVersion.parse_status,
                    Policy.authority_level,
                    Policy.department_scope,
                    Policy.policy_type,
                    rank.label("score"),
                )
                .select_from(PolicySection)
                .join(
                    PolicyVersion, PolicyVersion.id == PolicySection.policy_version_id
                )
                .join(Policy, Policy.id == PolicyVersion.policy_id)
                .where(PolicySection.tenant_id == tenant_id)
                .where(PolicyVersion.parse_status == ParseStatus.READY.value)
                .where(version_predicate)
                .where(tsv.op("@@")(tsquery))
                .order_by(rank.desc())
                .limit(limit_value)
            )

            if policy_ids:
                stmt = stmt.where(Policy.id.in_(policy_ids))
            if policy_types:
                effective_policy_type = func.coalesce(
                    Policy.policy_type,
                    PolicyVersion.metadata_json.op("->>")("policy_type"),
                    PolicyVersion.metadata_json.op("->>")("type"),
                )
                stmt = stmt.where(effective_policy_type.in_(policy_types))
            return stmt

        rows = self._session.execute(_build_stmt(and_tsquery)).all()
        if (not rows) and (or_tsquery is not None):
            rows = self._session.execute(_build_stmt(or_tsquery)).all()
        results: list[EvidenceCandidate] = []
        for row in rows:
            results.append(
                EvidenceCandidate(
                    policy_id=row.policy_id,
                    policy_version_id=row.policy_version_id,
                    section_id=row.id,
                    text=row.text,
                    score=float(row.score or 0.0),
                    source="pgsql_fts",
                    metadata={
                        "section_path": row.section_path,
                        "title": row.title,
                        "policy_name": row.policy_name,
                        "public_url": row.public_url,
                        "section_index": int(row.section_index or 0),
                        "retriever": "pgsql_fts",
                        "is_current": True
                        if as_of is not None
                        else bool(row.is_current),
                        "version_label": row.version_label,
                        "as_of": as_of.isoformat() if as_of is not None else None,
                        "effective_date": (
                            row.effective_date.isoformat()
                            if row.effective_date
                            else None
                        ),
                        "authority_level": int(row.authority_level or 0),
                        "department_scope": str(row.department_scope or "all"),
                        "policy_type": row.policy_type,
                        "user_department": user_department,
                    },
                )
            )
        return results
