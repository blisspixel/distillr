"""Installed-model suggestion stays offline."""

from __future__ import annotations

from distill.commands._local_model_choice import suggest_installed_model


def test_empty_inventory_returns_empty() -> None:
    assert suggest_installed_model([]) == ""
    assert suggest_installed_model([" ", ""], rates={}) == ""


def test_without_rates_picks_the_smallest_size_hint() -> None:
    chosen = suggest_installed_model(
        ["qwen3.5:27b", "gemma4:e4b", "custom"],
        rates={},
    )
    assert chosen == "gemma4:e4b"


def test_equal_sizes_break_ties_by_name() -> None:
    assert suggest_installed_model(["b:8b", "a:8b"], rates={}) == "a:8b"


def test_positive_rates_restrict_the_pool() -> None:
    chosen = suggest_installed_model(
        ["gemma4:e4b", "qwen3.5:27b"],
        rates={"qwen3.5:27b": 10.0, "gemma4:e4b": 0.0},
    )
    assert chosen == "qwen3.5:27b"


def test_sizes_override_the_name_hint() -> None:
    chosen = suggest_installed_model(
        ["huge:1b", "tiny:99b"],
        sizes={"huge:1b": 30.0, "tiny:99b": 2.0},
        rates={},
    )
    assert chosen == "tiny:99b"


def test_missing_rates_argument_reads_stored_history(monkeypatch) -> None:
    monkeypatch.setattr(
        "distill.commands.bench.stored_decode_rates",
        lambda: {"qwen3.5:27b": 4.0},
    )
    assert suggest_installed_model(["gemma4:e4b", "qwen3.5:27b"]) == "qwen3.5:27b"
