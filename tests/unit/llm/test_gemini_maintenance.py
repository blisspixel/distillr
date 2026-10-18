from datetime import date

import pytest

from distill.llm import cost, model_policy
from distill.llm.router import ConfigurationError, RouterConfig


@pytest.mark.parametrize(
    "day,model,expected",
    [
        (date(2026, 11, 30), "gemini-4-argon", {"input": 2.0, "output": 10.0}),
        (date(2026, 12, 1), "gemini-4-argon", {"input": 4.0, "output": 20.0}),
        (date(2026, 12, 31), "gemini-3.8-flash", {"input": 0.75, "output": 3.75}),
        (date(2027, 1, 1), "gemini-3.8-flash", {"input": 1.5, "output": 7.5}),
    ],
)
def test_published_price_boundaries(day, model, expected, monkeypatch):
    monkeypatch.setattr(cost, "_pricing_reference_date", lambda: day)
    assert cost.get_pricing(model) == expected
    assert cost.compute_cost(model, 1_000_000, 1_000_000) == sum(expected.values())


def test_shutdown_refuses_new_execution_but_preserves_historical_cost(monkeypatch):
    slug = "deep-research-pro-preview-12-2025"
    assert not model_policy.scheduled_model_refusal(slug, today=date(2026, 10, 22))
    refusal = model_policy.scheduled_model_refusal(slug, today=date(2026, 10, 23))
    assert "deep-research-preview-04-2026" in refusal
    assert cost.has_known_pricing(slug)
    monkeypatch.setattr("distill.llm.router.scheduled_model_refusal", lambda _: refusal)
    with pytest.raises(ConfigurationError, match="2026-10-23"):
        RouterConfig(provider="gemini", model=slug).resolve("analysis")
