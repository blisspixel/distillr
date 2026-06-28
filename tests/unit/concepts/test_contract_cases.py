"""Generated contract tests for deterministic concept helpers."""

from __future__ import annotations

import deal

from distill.concepts.normalize import canonicalize
from distill.concepts.recovery import parse_note_fields
from distill.library.paths import sanitize_path_component, sanitize_topic, slugify_title


def test_parse_note_fields_generated_contract_cases() -> None:
    """Arbitrary note text must satisfy the parser's structural postcondition."""
    for case in deal.cases(parse_note_fields, count=50, check_types=False, seed=20260627):
        case()


def test_canonicalize_generated_contract_cases() -> None:
    """Arbitrary concept names must satisfy the canonical idempotence contract."""
    for case in deal.cases(canonicalize, count=100, check_types=False, seed=20260628):
        case()


def test_path_sanitizer_generated_contract_cases() -> None:
    """Arbitrary path labels must stay confined to one path component."""
    targets = (slugify_title, sanitize_path_component, sanitize_topic)
    for offset, target in enumerate(targets):
        for case in deal.cases(target, count=50, check_types=False, seed=20260628 + offset):
            case()
