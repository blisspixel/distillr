"""Tests for distill.prompts.lenses and lens-driven analysis prompts."""

from __future__ import annotations

import pytest

from distill.prompts.analysis import pass2_synthesis_prompt
from distill.prompts.lenses import (
    DEFAULT_LENS,
    LENS_NAMES,
    focus_directive,
    normalize_lens,
    video_sections,
)
from distill.prompts.synthesis import paper_insight_prompt, site_page_insight_prompt


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("research", "research"),
        ("Research", "research"),
        ("competitive-intel", "general"),  # not a known name -> default
        ("competitive", "competitive"),
        ("", "general"),
        ("nonsense", "general"),
        ("  Academic ", "academic"),
    ],
)
def test_normalize_lens(raw, expected):
    assert normalize_lens(raw) == expected


def test_focus_directive_empty_for_neutral_default():
    # No lens + no goal must produce a byte-identical (empty) preamble so legacy
    # callers and the eval harness get unchanged prompts.
    assert focus_directive() == ""
    assert focus_directive(goal="", lens="general") == ""


def test_focus_directive_includes_stance_and_goal():
    block = focus_directive(goal="build OpenSteward", lens="research")
    assert "ANALYST LENS:" in block
    assert "research analyst" in block
    assert "GOAL FOCUS:" in block
    assert "build OpenSteward" in block


def test_focus_directive_caps_long_goal():
    block = focus_directive(goal="x " * 1000, lens="research")
    # Goal is collapsed and capped; the directive stays lean.
    assert len(block) < 1200


def test_video_sections_competitive_preserves_enterprise():
    competitive = video_sections("competitive")
    assert "Customer Conversation Starters" in competitive
    assert "Vendor Watch" in competitive
    assert "Business Value Signals" in competitive


def test_video_sections_default_drops_sales_framing():
    general = video_sections("general")
    assert "Customer Conversation Starters" not in general
    assert "Vendor Watch" not in general
    assert "Key Points" in general


def test_all_lenses_have_sections():
    for lens in LENS_NAMES:
        assert video_sections(lens).strip()
        assert "## Summary" in video_sections(lens)


def test_pass2_default_is_not_enterprise():
    prompt = pass2_synthesis_prompt("T", "20260101", "Creator", "facts")
    # The old hardcoded persona is gone from the default path.
    assert "pre-sales architect" not in prompt
    assert "Customer Conversation Starters" not in prompt


def test_pass2_competitive_lens_restores_enterprise():
    prompt = pass2_synthesis_prompt("T", "20260101", "Creator", "facts", lens="competitive")
    assert "Customer Conversation Starters" in prompt
    assert "pre-sales architect" in prompt


def test_pass2_research_lens_uses_research_sections():
    prompt = pass2_synthesis_prompt("T", "20260101", "Creator", "facts", lens="research", goal="g")
    assert "Claims and Findings" in prompt
    assert "Limitations and Open Questions" in prompt
    assert "GOAL FOCUS:" in prompt


def test_paper_insight_prompt_goal_lens_optional():
    base = paper_insight_prompt("Title", "2601.00001", "BODY")
    assert "ANALYST LENS" not in base  # neutral by default
    focused = paper_insight_prompt("Title", "2601.00001", "BODY", goal="g", lens="research")
    assert "ANALYST LENS" in focused
    assert "## Core Contribution" in focused  # sections preserved


def test_site_page_insight_prompt_goal_lens_optional():
    base = site_page_insight_prompt("T", "http://x", "Site", "doc", "BODY")
    assert "ANALYST LENS" not in base
    focused = site_page_insight_prompt(
        "T", "http://x", "Site", "doc", "BODY", goal="g", lens="practitioner"
    )
    assert "ANALYST LENS" in focused


def test_default_lens_constant():
    assert DEFAULT_LENS == "general"
    assert DEFAULT_LENS in LENS_NAMES
