# pyright: strict
"""Property tests for LLM_Response data model.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from distill.llm.router import LLM_Response


@settings(max_examples=100)
@given(
    text=st.text(),
    input_tokens=st.integers(min_value=0, max_value=10_000_000),
    output_tokens=st.integers(min_value=0, max_value=10_000_000),
    model=st.text(min_size=1, max_size=50),
)
def test_round_trip(text: str, input_tokens: int, output_tokens: int, model: str) -> None:
    """Feature: llm-router-model-upgrade, Property 1: LLM_Response round-trip

    For any valid combination of text, input_tokens, output_tokens, and model,
    constructing an LLM_Response and reading its fields back produces the same
    values that were passed in.

    **Validates: Requirements 3.1, 3.4**
    """
    response = LLM_Response(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )
    assert response.text == text
    assert response.input_tokens == input_tokens
    assert response.output_tokens == output_tokens
    assert response.model == model
    assert response.usage_source == "reported"
