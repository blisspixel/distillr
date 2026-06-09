"""Tests for distill.library.intent: CorpusIntent model + persistence."""

from __future__ import annotations

from distill.library.intent import (
    DEFAULT_RIGOR,
    CorpusIntent,
    intent_path,
    load_intent,
    make_intent,
    save_intent,
)


def test_make_intent_infers_lens_from_goal():
    intent = make_intent("I need a research corpus on prior art")
    assert intent.lens == "research"
    assert intent.goal == "I need a research corpus on prior art"
    assert intent.rigor == DEFAULT_RIGOR


def test_make_intent_explicit_lens_wins():
    intent = make_intent("how to build", lens="academic")
    assert intent.lens == "academic"


def test_make_intent_unknown_lens_falls_back_to_default():
    intent = make_intent("vendor pricing", lens="bogus")
    # Unknown explicit lens normalizes to general (does not silently infer).
    assert intent.lens == "general"


def test_make_intent_normalizes_rigor():
    assert make_intent("g", rigor="STRICT").rigor == "strict"
    assert make_intent("g", rigor="nonsense").rigor == DEFAULT_RIGOR


def test_save_and_load_roundtrip(tmp_path):
    intent = make_intent("build a steward", lens="research", audience="me", budget_usd=3.0)
    save_intent(tmp_path, intent)
    assert intent_path(tmp_path).exists()
    loaded = load_intent(tmp_path)
    assert loaded == CorpusIntent(
        goal="build a steward",
        lens="research",
        audience="me",
        rigor=DEFAULT_RIGOR,
        quality_bar="",
        budget_usd=3.0,
    )


def test_load_missing_returns_none(tmp_path):
    assert load_intent(tmp_path) is None


def test_load_malformed_returns_none(tmp_path):
    intent_path(tmp_path).write_text("{ not json", encoding="utf-8")
    assert load_intent(tmp_path) is None


def test_load_non_object_returns_none(tmp_path):
    intent_path(tmp_path).write_text("[1, 2, 3]", encoding="utf-8")
    assert load_intent(tmp_path) is None


def test_load_ignores_unknown_keys_and_bad_budget(tmp_path):
    intent_path(tmp_path).write_text(
        '{"goal": "g", "lens": "research", "surprise": 1, "budget_usd": "lots"}',
        encoding="utf-8",
    )
    loaded = load_intent(tmp_path)
    assert loaded is not None
    assert loaded.goal == "g"
    assert loaded.lens == "research"
    assert loaded.budget_usd is None  # non-numeric budget dropped, not crashing


def test_corpus_intent_is_frozen():
    intent = make_intent("g")
    try:
        intent.goal = "x"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("CorpusIntent should be frozen")
