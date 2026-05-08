# pyright: strict
"""Property tests for RouterConfig environment variable construction.

Feature: living-wiki-0-7, Property 10: RouterConfig environment variable construction

Tests that for any valid set of DISTILL_-prefixed env vars, RouterConfig correctly
maps each to its corresponding field, respecting the resolution precedence
(per-workload override > tier default > global default).
"""

from __future__ import annotations

import os
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from distill.llm.router import WORKLOAD_TAGS, RouterConfig

# --- Strategies ---

# Non-empty model identifiers (alphanumeric with dots and dashes)
_model_str = st.from_regex(r"[a-z][a-z0-9\.\-]{0,29}", fullmatch=True)

# Provider names
_provider_str = st.sampled_from(["xai", "gemini", "anthropic", "openai", "ollama", "lmstudio"])

# Workload tags
_workload_tags = st.sampled_from(sorted(WORKLOAD_TAGS))

# API key strings (non-empty alphanumeric)
_api_key_str = st.from_regex(r"[a-zA-Z0-9]{8,40}", fullmatch=True)


class TestRouterConfigEnvVarMapping:
    """Property 10: RouterConfig environment variable construction.

    **Validates: Requirements 8.4**
    """

    @settings(max_examples=100)
    @given(
        provider=_provider_str,
        fast_model=_model_str,
        premium_model=_model_str,
    )
    def test_distill_prefixed_env_vars_map_to_fields(
        self,
        provider: str,
        fast_model: str,
        premium_model: str,
    ) -> None:
        """For any valid DISTILL_-prefixed env vars, RouterConfig maps each to its field.

        Feature: living-wiki-0-7, Property 10: RouterConfig environment variable construction
        **Validates: Requirements 8.4**
        """
        env = {
            "DISTILL_PROVIDER": provider,
            "DISTILL_FAST_MODEL": fast_model,
            "DISTILL_PREMIUM_MODEL": premium_model,
        }
        with patch.dict(os.environ, env, clear=True):
            rc = RouterConfig()

        assert rc.provider == provider
        assert rc.fast_model == fast_model
        assert rc.premium_model == premium_model

    @settings(max_examples=100)
    @given(
        xai_key=_api_key_str,
        gemini_key=_api_key_str,
        anthropic_key=_api_key_str,
        openai_key=_api_key_str,
    )
    def test_api_keys_read_from_non_prefixed_env_vars(
        self,
        xai_key: str,
        gemini_key: str,
        anthropic_key: str,
        openai_key: str,
    ) -> None:
        """API keys are read from their canonical non-prefixed env var names.

        Feature: living-wiki-0-7, Property 10: RouterConfig environment variable construction
        **Validates: Requirements 8.4**
        """
        env = {
            "XAI_API_KEY": xai_key,
            "GEMINI_API_KEY": gemini_key,
            "ANTHROPIC_API_KEY": anthropic_key,
            "OPENAI_API_KEY": openai_key,
        }
        with patch.dict(os.environ, env, clear=True):
            rc = RouterConfig()

        assert rc.xai_api_key == xai_key
        assert rc.gemini_api_key == gemini_key
        assert rc.anthropic_api_key == anthropic_key
        assert rc.openai_api_key == openai_key

    @settings(max_examples=100)
    @given(
        workload_tag=_workload_tags,
        per_workload_model=_model_str,
        fast_model=_model_str,
        premium_model=_model_str,
    )
    def test_per_workload_model_override_takes_precedence(
        self,
        workload_tag: str,
        per_workload_model: str,
        fast_model: str,
        premium_model: str,
    ) -> None:
        """Per-workload model override > tier default > global default.

        Feature: living-wiki-0-7, Property 10: RouterConfig environment variable construction
        **Validates: Requirements 8.4**
        """
        env = {
            "DISTILL_FAST_MODEL": fast_model,
            "DISTILL_PREMIUM_MODEL": premium_model,
            f"DISTILL_{workload_tag.upper()}_MODEL": per_workload_model,
        }
        with patch.dict(os.environ, env, clear=True):
            rc = RouterConfig()

        _, resolved_model = rc.resolve(workload_tag)
        assert resolved_model == per_workload_model, (
            f"Per-workload override '{per_workload_model}' should win over "
            f"tier defaults (fast={fast_model}, premium={premium_model})"
        )

    @settings(max_examples=100)
    @given(
        workload_tag=_workload_tags,
        fast_model=_model_str,
        premium_model=_model_str,
    )
    def test_tier_default_used_when_no_per_workload_override(
        self,
        workload_tag: str,
        fast_model: str,
        premium_model: str,
    ) -> None:
        """When no per-workload override, tier default is used.

        Premium workloads use premium_model, others use fast_model.

        Feature: living-wiki-0-7, Property 10: RouterConfig environment variable construction
        **Validates: Requirements 8.4**
        """
        env = {
            "DISTILL_FAST_MODEL": fast_model,
            "DISTILL_PREMIUM_MODEL": premium_model,
        }
        with patch.dict(os.environ, env, clear=True):
            rc = RouterConfig()

        _, resolved_model = rc.resolve(workload_tag)

        if workload_tag in rc.PREMIUM_WORKLOADS:
            assert resolved_model == premium_model, (
                f"Premium workload '{workload_tag}' should use premium_model '{premium_model}'"
            )
        else:
            assert resolved_model == fast_model, (
                f"Non-premium workload '{workload_tag}' should use fast_model '{fast_model}'"
            )

    @settings(max_examples=100)
    @given(
        workload_tag=_workload_tags,
        per_workload_provider=_provider_str,
        global_provider=_provider_str,
    )
    def test_per_workload_provider_override_takes_precedence(
        self,
        workload_tag: str,
        per_workload_provider: str,
        global_provider: str,
    ) -> None:
        """Per-workload provider override > global provider.

        Feature: living-wiki-0-7, Property 10: RouterConfig environment variable construction
        **Validates: Requirements 8.4**
        """
        env = {
            "DISTILL_PROVIDER": global_provider,
            f"DISTILL_{workload_tag.upper()}_PROVIDER": per_workload_provider,
        }
        with patch.dict(os.environ, env, clear=True):
            rc = RouterConfig()

        resolved_provider, _ = rc.resolve(workload_tag)
        assert resolved_provider == per_workload_provider, (
            f"Per-workload provider '{per_workload_provider}' should win over "
            f"global provider '{global_provider}'"
        )

    @settings(max_examples=100)
    @given(
        workload_tag=_workload_tags,
        global_provider=_provider_str,
    )
    def test_global_provider_used_when_no_per_workload_override(
        self,
        workload_tag: str,
        global_provider: str,
    ) -> None:
        """When no per-workload provider override, global provider is used.

        Feature: living-wiki-0-7, Property 10: RouterConfig environment variable construction
        **Validates: Requirements 8.4**
        """
        env = {
            "DISTILL_PROVIDER": global_provider,
        }
        with patch.dict(os.environ, env, clear=True):
            rc = RouterConfig()

        resolved_provider, _ = rc.resolve(workload_tag)
        assert resolved_provider == global_provider, (
            f"Global provider '{global_provider}' should be used for '{workload_tag}'"
        )

    @settings(max_examples=100)
    @given(
        model_override=_model_str,
        fast_model=_model_str,
        premium_model=_model_str,
        workload_tag=_workload_tags,
    )
    def test_distill_model_env_var_overrides_all_workloads(
        self,
        model_override: str,
        fast_model: str,
        premium_model: str,
        workload_tag: str,
    ) -> None:
        """DISTILL_MODEL env var overrides all workload model resolution.

        Feature: living-wiki-0-7, Property 10: RouterConfig environment variable construction
        **Validates: Requirements 8.4**
        """
        env = {
            "DISTILL_MODEL": model_override,
            "DISTILL_FAST_MODEL": fast_model,
            "DISTILL_PREMIUM_MODEL": premium_model,
        }
        with patch.dict(os.environ, env, clear=True):
            rc = RouterConfig()

        _, resolved_model = rc.resolve(workload_tag)
        assert resolved_model == model_override, (
            f"DISTILL_MODEL '{model_override}' should override all workloads, "
            f"got '{resolved_model}' for '{workload_tag}'"
        )
