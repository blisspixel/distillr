# pyright: strict
"""Property tests for RouterConfig resolution logic.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from distill.llm.router import WORKLOAD_TAGS, RouterConfig

# Strategy: pick a workload tag that has corresponding model/provider fields
_workload_tags = st.sampled_from(sorted(WORKLOAD_TAGS))

# Strategy: non-empty model string (simulates a real model identifier)
_model_str = st.from_regex(r"[a-z0-9\-\.]{1,30}", fullmatch=True)

# Strategy: provider name (non-empty)
_provider_str = st.from_regex(r"[a-z]{1,20}", fullmatch=True)


@settings(max_examples=100)
@given(
    workload_tag=_workload_tags,
    per_workload_model=st.one_of(st.just(""), _model_str),
    fast_model=_model_str,
    premium_model=_model_str,
    is_premium=st.booleans(),
)
def test_model_resolution_hierarchy(
    workload_tag: str,
    per_workload_model: str,
    fast_model: str,
    premium_model: str,
    is_premium: bool,
) -> None:
    """Feature: llm-router-model-upgrade, Property 2: Configuration resolution hierarchy for models

    For any RouterConfig with arbitrary per-workload model overrides, tier
    defaults, and workload tags, resolve() returns the per-workload model
    override when non-empty, the premium tier model when the workload is in
    PREMIUM_WORKLOADS and no override is set, and the fast tier model otherwise.

    **Validates: Requirements 1.2**
    """
    # Build PREMIUM_WORKLOADS: either include the current tag or not
    premium_workloads: tuple[str, ...] = (workload_tag,) if is_premium else ()

    kwargs: dict[str, object] = {
        "fast_model": fast_model,
        "premium_model": premium_model,
        "PREMIUM_WORKLOADS": premium_workloads,
    }
    # Set the per-workload model override if non-empty
    if per_workload_model:
        kwargs[f"{workload_tag}_model"] = per_workload_model

    config = RouterConfig(**kwargs)  # type: ignore[arg-type]
    _, model_id = config.resolve(workload_tag)

    if per_workload_model:
        assert model_id == per_workload_model, (
            f"Per-workload override '{per_workload_model}' should win, got '{model_id}'"
        )
    elif workload_tag in premium_workloads:
        assert model_id == premium_model, (
            f"Premium tier '{premium_model}' should win for '{workload_tag}', got '{model_id}'"
        )
    else:
        assert model_id == fast_model, (
            f"Fast tier '{fast_model}' should win for '{workload_tag}', got '{model_id}'"
        )


@settings(max_examples=100)
@given(
    workload_tag=_workload_tags,
    global_provider=_provider_str,
    per_workload_provider=st.one_of(st.just(""), _provider_str),
)
def test_provider_resolution(
    workload_tag: str,
    global_provider: str,
    per_workload_provider: str,
) -> None:
    """Feature: llm-router-model-upgrade, Property 8: Per-workload provider override resolution

    For any RouterConfig with arbitrary global provider and per-workload
    provider overrides, resolve() returns the per-workload provider override
    when non-empty, and the global provider otherwise.

    **Validates: Requirements 10.3, 10.4**
    """
    kwargs: dict[str, object] = {
        "provider": global_provider,
    }
    if per_workload_provider:
        kwargs[f"{workload_tag}_provider"] = per_workload_provider

    config = RouterConfig(**kwargs)  # type: ignore[arg-type]
    provider_name, _ = config.resolve(workload_tag)

    if per_workload_provider:
        assert provider_name == per_workload_provider, (
            f"Per-workload provider '{per_workload_provider}' should win, got '{provider_name}'"
        )
    else:
        assert provider_name == global_provider, (
            f"Global provider '{global_provider}' should win, got '{provider_name}'"
        )
