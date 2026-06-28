"""Generated contract tests for deterministic concept helpers."""

from __future__ import annotations

import deal

from distill.concepts.recovery import parse_note_fields


def test_parse_note_fields_generated_contract_cases() -> None:
    """Arbitrary note text must satisfy the parser's structural postcondition."""
    for case in deal.cases(parse_note_fields, count=50, check_types=False, seed=20260627):
        case()
