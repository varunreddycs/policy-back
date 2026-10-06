"""S3: NIST control IDs as first-class citation fields."""

from __future__ import annotations

import pytest

from packages.core import control_ids as core_ids
from packages.core.control_ids import primary_control_id, strip_control_prefix
from packages.rag.answer_service import _citation_control


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("AC-2(3) Disable Accounts", "AC-2(3)"),
        ("ac-02", "AC-2"),
        ("see AC-2 and IA-5", "AC-2"),
        # First by position; a set-ordered implementation could return AC-2.
        ("SC-7 then AC-2", "SC-7"),
        ("3.2", None),
        (None, None),
        ("", None),
    ],
)
def test_primary_control_id(text: str | None, expected: str | None) -> None:
    assert primary_control_id(text) == expected


@pytest.mark.parametrize(
    ("title", "control_id", "expected"),
    [
        ("AC-2 Account Management", "AC-2", "Account Management"),
        ("AC-2(3) Disable Accounts", "AC-2(3)", "Disable Accounts"),
        ("ac-02 - Account Management", "AC-2", "Account Management"),
        ("Account Management", "AC-2", "Account Management"),
        ("AC-2", "AC-2", None),
        (None, "AC-2", None),
    ],
)
def test_strip_control_prefix(
    title: str | None, control_id: str, expected: str | None
) -> None:
    assert strip_control_prefix(title, control_id) == expected


@pytest.mark.parametrize(
    ("md", "expected"),
    [
        (
            {"section_path": "AC-2(3)", "title": "Disable Accounts"},
            ("AC-2(3)", "Disable Accounts"),
        ),
        (
            {"section_path": "AC-2", "title": "AC-2 Account Management"},
            ("AC-2", "Account Management"),
        ),
        # A control mentioned only in the title must not become the citation's
        # control: "Implementing AC-2" under path 3.2 is not AC-2 itself.
        ({"section_path": "3.2", "title": "Implementing AC-2"}, (None, None)),
        (
            {"section_path": "chunk-3", "control_id": "ia-05(1)", "title": "x"},
            ("IA-5(1)", "x"),
        ),
        ({}, (None, None)),
    ],
)
def test_citation_control(
    md: dict[str, str], expected: tuple[str | None, str | None]
) -> None:
    assert _citation_control(md) == expected


def test_retrieval_module_reexports_core_functions() -> None:
    from packages.retrieval.control_ids import (
        extract_control_ids,
        normalize_control_ids,
    )

    assert extract_control_ids is core_ids.extract_control_ids
    assert normalize_control_ids is core_ids.normalize_control_ids


@pytest.mark.parametrize(
    "md",
    [
        {"section_path": "HR-4", "title": "HR-4 Leave Of Absence"},
        {"section_path": "US-1", "title": "Some Title"},
        {"section_path": "chunk-3", "control_id": "XY-9"},
    ],
)
def test_citation_control_rejects_non_nist_families(md: dict[str, str]) -> None:
    # Same shape as a NIST control, but not one. Labeling a department clause
    # as a NIST control is the mislabeling the no-fallback rule exists to prevent.
    assert _citation_control(md) == (None, None)


def test_every_rev5_family_is_accepted() -> None:
    from packages.core.control_ids import NIST_800_53_FAMILIES, is_nist_control_id

    assert len(NIST_800_53_FAMILIES) == 20
    assert all(is_nist_control_id(f"{fam}-1") for fam in NIST_800_53_FAMILIES)
    assert not is_nist_control_id(None)
