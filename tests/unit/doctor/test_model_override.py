"""Unit tests for --model CLI override and RouterConfig.with_model_override."""

from __future__ import annotations

from distill.llm.router import RouterConfig


class TestWithModelOverride:
    """Tests for the RouterConfig.with_model_override method."""

    def test_override_sets_fast_and_premium(self) -> None:
        config = RouterConfig(
            xai_api_key="test",
            fast_model="grok-4.3",
            premium_model="grok-4.3",
        )
        result = config.with_model_override("qwen3.5:27b")
        assert result.fast_model == "qwen3.5:27b"
        assert result.premium_model == "qwen3.5:27b"

    def test_empty_override_returns_same_config(self) -> None:
        config = RouterConfig(
            xai_api_key="test",
            fast_model="grok-4.3",
            premium_model="grok-4.3",
        )
        result = config.with_model_override("")
        assert result.fast_model == "grok-4.3"
        assert result.premium_model == "grok-4.3"

    def test_override_preserves_other_fields(self) -> None:
        config = RouterConfig(
            xai_api_key="test-key",
            provider="ollama",
            fast_model="grok-4.3",
            premium_model="grok-4.3",
            ops_dir="/tmp/ops",
        )
        result = config.with_model_override("custom-model:7b")
        assert result.xai_api_key == "test-key"
        assert result.provider == "ollama"
        assert result.ops_dir == "/tmp/ops"
        assert result.fast_model == "custom-model:7b"
        assert result.premium_model == "custom-model:7b"

    def test_override_affects_resolve(self) -> None:
        config = RouterConfig(
            provider="ollama",
            fast_model="grok-4.3",
            premium_model="grok-4.3",
        )
        result = config.with_model_override("qwen3.5:14b")
        _, model = result.resolve("analysis")
        assert model == "qwen3.5:14b"

    def test_override_affects_premium_workloads(self) -> None:
        config = RouterConfig(
            provider="ollama",
            fast_model="grok-4.3",
            premium_model="grok-4.3",
        )
        result = config.with_model_override("qwen3.5:14b")
        _, model = result.resolve("report")  # premium workload
        assert model == "qwen3.5:14b"
