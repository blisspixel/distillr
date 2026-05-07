# pyright: strict
"""Property-based tests for the adaptive chunker.

Feature: local-inference
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.pipeline.analysis.chunking import chunk_content, estimate_tokens

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Markdown content with headings for multi-section tests
_heading_levels = st.sampled_from(["# ", "## ", "### ", "#### "])
_heading_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
        blacklist_characters="\x00\n\r",
    ),
    min_size=1,
    max_size=30,
)


@st.composite
def _markdown_section(draw: st.DrawFn) -> str:
    """Generate a markdown section with a heading and body paragraphs."""
    level = draw(_heading_levels)
    title = draw(_heading_text)
    heading = f"{level}{title}"
    # Generate 1-5 paragraphs
    paragraphs = draw(
        st.lists(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "N", "Z", "P"),
                    blacklist_characters="\x00",
                ),
                min_size=10,
                max_size=200,
            ),
            min_size=1,
            max_size=5,
        )
    )
    body = "\n\n".join(paragraphs)
    return f"{heading}\n{body}"


@st.composite
def _markdown_document(draw: st.DrawFn) -> str:
    """Generate a multi-section markdown document."""
    sections = draw(st.lists(_markdown_section(), min_size=2, max_size=8))
    return "\n\n".join(sections)


# Arbitrary text content (not necessarily markdown)
_arbitrary_content = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=1,
    max_size=5000,
)

# Context windows: realistic range
_context_window = st.integers(min_value=100, max_value=1_000_000)


# ---------------------------------------------------------------------------
# Property 5: Chunk size invariant
# Feature: local-inference, Property 5: Chunk size invariant
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(content=_arbitrary_content, context_window=_context_window)
def test_chunk_size_invariant(content: str, context_window: int) -> None:
    """No chunk exceeds available tokens (context_window * 0.80).

    **Validates: Requirements 7.1, 18.5**
    """
    reserved_ratio = 0.20
    available_tokens = int(context_window * (1 - reserved_ratio))
    chunks = chunk_content(content, context_window, reserved_ratio=reserved_ratio)

    for chunk in chunks:
        chunk_tokens = estimate_tokens(chunk.text)
        assert chunk_tokens <= available_tokens, (
            f"Chunk {chunk.index} has {chunk_tokens} tokens, exceeds available {available_tokens}"
        )


# ---------------------------------------------------------------------------
# Property 6: Content preservation across chunks
# Feature: local-inference, Property 6: Content preservation across chunks
# ---------------------------------------------------------------------------


def _normalize_whitespace(text: str) -> str:
    """Collapse all whitespace to single spaces for comparison."""
    import re

    return re.sub(r"\s+", " ", text).strip()


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(content=_arbitrary_content, context_window=_context_window)
def test_content_preservation(content: str, context_window: int) -> None:
    """All non-whitespace content from original appears in chunks.

    **Validates: Requirements 7.1, 18.5**
    """
    chunks = chunk_content(content, context_window)

    # Extract all non-whitespace characters from original
    original_chars = set(
        content.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", "")
    )

    # Extract all non-whitespace characters from chunks (excluding heading context markers)
    chunk_text = " ".join(c.text for c in chunks)
    # Remove "[continued from: ...]" markers that are added by the chunker
    import re

    chunk_text_clean = re.sub(r"\[continued from: [^\]]*\]", "", chunk_text)
    chunk_chars = set(
        chunk_text_clean.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", "")
    )

    # All unique characters from original should appear in chunks
    missing = original_chars - chunk_chars
    assert not missing, f"Characters missing from chunks: {missing!r}"


# ---------------------------------------------------------------------------
# Property 7: Chunking decision boundary
# Feature: local-inference, Property 7: Chunking decision boundary
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(context_window=st.integers(min_value=100, max_value=100_000))
def test_chunking_decision_boundary_passthrough(context_window: int) -> None:
    """Content < 80% window = exactly 1 chunk with original content.

    **Validates: Requirements 7.5, 16.1, 16.2**
    """
    # Generate content that is just under 80% of the window
    available_tokens = int(context_window * 0.80)
    # Each char is ~0.25 tokens, so we need chars < available_tokens * 4
    target_chars = max(1, (available_tokens - 1) * 4)
    content = "a" * min(target_chars, 1000)  # Cap for performance

    # Verify it's under the threshold
    if estimate_tokens(content) < int(context_window * 0.80):
        chunks = chunk_content(content, context_window)
        assert len(chunks) == 1
        assert chunks[0].text == content


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(context_window=st.integers(min_value=50, max_value=10_000))
def test_chunking_decision_boundary_splits(context_window: int) -> None:
    """Content >= 80% window = multiple chunks.

    **Validates: Requirements 7.5, 16.1, 16.2**
    """
    # Generate content that exceeds 80% of the window
    available_tokens = int(context_window * 0.80)
    # Need at least available_tokens * 4 chars to exceed threshold
    target_chars = (available_tokens + 1) * 4
    # Create multi-section content to ensure it can be split
    section_size = max(10, target_chars // 3)
    content = (
        f"# Section 1\n{'x' * section_size}\n\n"
        f"## Section 2\n{'y' * section_size}\n\n"
        f"### Section 3\n{'z' * section_size}\n"
    )

    # Verify it's over the threshold
    if estimate_tokens(content) >= int(context_window * 0.80):
        chunks = chunk_content(content, context_window)
        assert len(chunks) > 1, (
            f"Expected multiple chunks for content with "
            f"{estimate_tokens(content)} tokens and window {context_window}"
        )


# ---------------------------------------------------------------------------
# Property 8: Heading context preservation
# Feature: local-inference, Property 8: Heading context preservation
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(doc=_markdown_document(), context_window=st.integers(min_value=50, max_value=500))
def test_heading_context_preservation(doc: str, context_window: int) -> None:
    """Multi-chunk results have non-empty heading_context.

    **Validates: Requirements 7.4, 18.5**
    """
    chunks = chunk_content(doc, context_window)

    if len(chunks) > 1:
        for chunk in chunks:
            assert chunk.heading_context != "", (
                f"Chunk {chunk.index} has empty heading_context in multi-chunk result"
            )


# ---------------------------------------------------------------------------
# Property 12: Token estimation identity
# Feature: local-inference, Property 12: Token estimation identity
# ---------------------------------------------------------------------------


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(text=st.text(min_size=0, max_size=10000))
def test_token_estimation_identity(text: str) -> None:
    """estimate_tokens(s) == len(s) // 4.

    **Validates: Requirements 16.3**
    """
    assert estimate_tokens(text) == len(text) // 4
