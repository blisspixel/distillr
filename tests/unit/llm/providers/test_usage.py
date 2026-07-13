"""Contracts for conservative provider usage normalization."""

from distill.llm.providers._usage import combined_output_usage, usage_or_conservative


def test_preserves_valid_reported_usage() -> None:
    assert usage_or_conservative(
        12,
        7,
        prompt="question",
        output_text="answer",
        max_tokens=100,
    ) == (12, 7, False)


def test_replaces_inconsistent_zero_usage_with_upper_bounds() -> None:
    assert usage_or_conservative(
        0,
        0,
        prompt="question",
        output_text="answer",
        max_tokens=100,
    ) == (1032, 100, True)


def test_empty_input_and_output_may_report_zero_usage() -> None:
    assert usage_or_conservative(
        0,
        0,
        prompt="",
        output_text="",
        max_tokens=100,
    ) == (0, 0, False)


def test_oversized_reported_usage_falls_back_without_overflow() -> None:
    assert usage_or_conservative(
        10**400,
        1,
        prompt="question",
        output_text="answer",
        max_tokens=100,
    ) == (1032, 1, True)
    assert combined_output_usage(10**12, 1, output_text="answer") is None
