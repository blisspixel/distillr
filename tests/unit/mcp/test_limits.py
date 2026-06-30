"""Tests for MCP costly-tool limit clamping (cost-DoS guard)."""

from __future__ import annotations

from distill.mcp.tools.discover import _MAX_LIMIT, _clamp_limit


def test_clamp_limit_bounds_and_defaults() -> None:
    # A prompt-injected agent passing a huge limit must be clamped so it can't
    # drive unbounded transcript downloads + LLM spend.
    assert _clamp_limit(100_000) == _MAX_LIMIT
    assert _clamp_limit(0) == 1
    assert _clamp_limit(-5) == 1
    assert _clamp_limit(7) == 7
    assert _clamp_limit("bad") == 5  # type: ignore[arg-type]
    assert _clamp_limit(False) == 5
