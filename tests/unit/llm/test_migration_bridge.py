"""Unit tests for the DistillConfig → RouterConfig migration bridge."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.config import DistillConfig, router_config_from_distill


class TestRouterConfigFromDistill:
    """Tests for router_config_from_distill() factory function."""

    def test_legacy_only_env_vars_produce_correct_router_config(self, tmp_path: Path):
        """Legacy DistillConfig fields map to the right RouterConfig fields."""
        config = DistillConfig(
            xai_api_key="xai-key-123",
            gemini_api_key="gem-key-456",
            openai_api_key="oai-key-789",
            distill_output_dir=tmp_path,
            xai_fast_model="grok-4.3",
            xai_premium_model="grok-4.3",
            xai_analysis_model="custom-analysis",
            xai_rerank_model="",
            xai_synthesis_model="custom-synth",
            xai_site_model="grok-4.20-0309-reasoning",
            accordion_section_model="grok-4-1-fast-reasoning",
        )
        # No new env vars set — only legacy
        with patch.dict(os.environ, {}, clear=True):
            rc = router_config_from_distill(config)

        assert rc.xai_api_key == "xai-key-123"
        assert rc.gemini_api_key == "gem-key-456"
        assert rc.openai_api_key == "oai-key-789"
        assert rc.fast_model == "grok-4.3"
        assert rc.premium_model == "grok-4.3"
        assert rc.analysis_model == "custom-analysis"
        assert rc.rerank_model == ""
        assert rc.synthesis_model == "custom-synth"
        assert rc.site_model == "grok-4.20-0309-reasoning"
        assert rc.accordion_model == "grok-4-1-fast-reasoning"
        assert rc.brief_model == "custom-synth"  # brief uses synthesis model
        assert rc.provider == "xai"  # default

    def test_new_provider_override_env_vars(self, tmp_path: Path):
        """New DISTILL_PROVIDER and per-workload provider env vars are picked up."""
        config = DistillConfig(
            xai_api_key="key",
            distill_output_dir=tmp_path,
        )
        env = {
            "DISTILL_PROVIDER": "gemini",
            "DISTILL_ANALYSIS_PROVIDER": "anthropic",
            "DISTILL_SITE_PROVIDER": "agent",
            "ANTHROPIC_API_KEY": "ant-key-abc",
        }
        with patch.dict(os.environ, env, clear=True):
            rc = router_config_from_distill(config)

        assert rc.provider == "gemini"
        assert rc.analysis_provider == "anthropic"
        assert rc.site_provider == "agent"
        assert rc.anthropic_api_key == "ant-key-abc"
        # Unset per-workload providers default to empty
        assert rc.rerank_provider == ""
        assert rc.synthesis_provider == ""

    def test_ops_dir_set_correctly(self, tmp_path: Path):
        """ops_dir is set to library_dir / '.distill'."""
        config = DistillConfig(
            xai_api_key="key",
            distill_output_dir=tmp_path,
        )
        with patch.dict(os.environ, {}, clear=True):
            rc = router_config_from_distill(config)

        expected = str(tmp_path / ".distill")
        assert rc.ops_dir == expected

    def test_xai_model_for_still_works(self, tmp_path: Path):
        """DistillConfig.xai_model_for() still works during migration period."""
        config = DistillConfig(
            xai_api_key="key",
            distill_output_dir=tmp_path,
            xai_fast_model="grok-4.3",
            xai_premium_model="grok-4.3",
            xai_analysis_model="custom-analysis",
            xai_site_model="grok-4.20-0309-reasoning",
        )
        # Per-workload override
        assert config.xai_model_for("analysis") == "custom-analysis"
        # Premium workload with override
        assert config.xai_model_for("site") == "grok-4.20-0309-reasoning"
        # Fast workload with no override
        assert config.xai_model_for("rerank") == "grok-4.3"
        # Synthesis with no override
        assert config.xai_model_for("synthesis") == "grok-4.3"
        # Unknown workload falls back to fast
        assert config.xai_model_for("unknown") == "grok-4.3"

    def test_default_model_values_updated(self):
        """DistillConfig defaults are now grok-4.3."""
        config = DistillConfig(xai_api_key="key")
        assert config.xai_fast_model == "grok-4.3"
        assert config.xai_premium_model == "grok-4.3"

    def test_all_per_workload_provider_env_vars(self, tmp_path: Path):
        """All per-workload provider env vars are read."""
        config = DistillConfig(xai_api_key="key", distill_output_dir=tmp_path)
        env = {
            "DISTILL_ANALYSIS_PROVIDER": "p1",
            "DISTILL_RERANK_PROVIDER": "p2",
            "DISTILL_SYNTHESIS_PROVIDER": "p3",
            "DISTILL_SITE_PROVIDER": "p4",
            "DISTILL_ACCORDION_PROVIDER": "p5",
            "DISTILL_BRIEF_PROVIDER": "p6",
            "DISTILL_REPORT_PROVIDER": "p7",
            "DISTILL_QA_PROVIDER": "p8",
            "DISTILL_MAINTENANCE_PROVIDER": "p9",
        }
        with patch.dict(os.environ, env, clear=True):
            rc = router_config_from_distill(config)

        assert rc.analysis_provider == "p1"
        assert rc.rerank_provider == "p2"
        assert rc.synthesis_provider == "p3"
        assert rc.site_provider == "p4"
        assert rc.accordion_provider == "p5"
        assert rc.brief_provider == "p6"
        assert rc.report_provider == "p7"
        assert rc.qa_provider == "p8"
        assert rc.maintenance_provider == "p9"
