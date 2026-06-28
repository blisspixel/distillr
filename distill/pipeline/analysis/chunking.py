# pyright: strict
"""Adaptive content chunker for local model context windows.

Splits content at section boundaries when it exceeds the provider's
context window. Preserves heading context in each chunk for positional
awareness. Passes through unchanged when content fits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Chunk", "chunk_content", "estimate_tokens"]


@dataclass(frozen=True)
class Chunk:
    """A section-aware content chunk."""

    text: str
    heading_context: str  # parent headings for positional awareness
    index: int  # position in original document
    total_chunks: int  # total number of chunks produced


def estimate_tokens(text: str) -> int:
    """Fast token count approximation: 4 chars per token."""
    return len(text) // 4


def chunk_content(
    content: str,
    context_window: int,
    *,
    reserved_ratio: float = 0.20,
) -> list[Chunk]:
    """Split content into chunks that fit within the available window.

    Strategy:
    1. If content fits (< 80% of window), return single chunk (passthrough).
    2. Split at markdown heading boundaries.
    3. If a section exceeds the window, split at paragraph boundaries.
    4. Preserve heading context in each chunk.
    """
    available_tokens = int(context_window * (1 - reserved_ratio))

    # Guard against degenerate inputs
    if available_tokens <= 0:
        available_tokens = 1

    content_tokens = estimate_tokens(content)

    # Passthrough: content fits
    if content_tokens < available_tokens:
        return [Chunk(text=content, heading_context="", index=0, total_chunks=1)]

    # Split at section boundaries
    sections = _split_into_sections(content)
    chunks: list[Chunk] = []
    current_heading = ""

    for heading, body in sections:
        if heading:
            current_heading = heading

        section_text = f"{heading}\n{body}" if heading else body
        if estimate_tokens(section_text) <= available_tokens:
            texts = [section_text.strip()]
        else:
            texts = _split_oversized_section(heading, body, current_heading, available_tokens)

        for text in texts:
            chunks.append(
                Chunk(
                    text=text,
                    heading_context=current_heading,
                    index=len(chunks),
                    total_chunks=0,  # will be updated
                )
            )

    # Update total_chunks
    total = len(chunks)
    chunks = [
        Chunk(
            text=c.text,
            heading_context=c.heading_context,
            index=c.index,
            total_chunks=total,
        )
        for c in chunks
    ]

    return chunks if chunks else [Chunk(text=content, heading_context="", index=0, total_chunks=1)]


def _split_into_sections(content: str) -> list[tuple[str, str]]:
    """Split markdown content into (heading, body) tuples."""
    lines = content.split("\n")
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_body: list[str] = []

    for line in lines:
        if re.match(r"^#{1,6}\s+", line):
            # New heading, flush previous section.
            if current_heading or current_body:
                sections.append((current_heading, "\n".join(current_body)))
            current_heading = line
            current_body = []
        else:
            current_body.append(line)

    # Flush last section
    if current_heading or current_body:
        sections.append((current_heading, "\n".join(current_body)))

    return sections


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs (double newline separated)."""
    paragraphs = re.split(r"\n\n+", text)
    return [p.strip() for p in paragraphs if p.strip()]


def _split_oversized_section(
    heading: str, body: str, current_heading: str, available_tokens: int
) -> list[str]:
    """Split a section that exceeds the window into within-budget chunk texts.

    Splits at paragraph boundaries, prefixing continuation chunks with a
    ``[continued from: ...]`` marker, and hard-splits any single paragraph that
    is itself larger than the whole window so no emitted chunk ever overflows.
    """
    texts: list[str] = []
    para_chunk = heading + "\n" if heading else ""

    for para in _split_into_paragraphs(body):
        candidate = para_chunk + para + "\n\n"
        if estimate_tokens(candidate) <= available_tokens:
            para_chunk = candidate
            continue

        # `candidate` overflows. Flush the accumulated chunk (if any), then
        # place this paragraph in fresh chunk(s).
        if para_chunk.strip():
            texts.append(para_chunk.strip())
        cont = f"[continued from: {current_heading}]\n"
        if estimate_tokens(cont + para + "\n\n") <= available_tokens:
            para_chunk = cont + para + "\n\n"
            continue

        # A single paragraph larger than the whole window: hard-split it.
        texts.extend(piece.strip() for piece in _hard_split_text(para, cont, available_tokens))
        para_chunk = ""

    if para_chunk.strip():
        texts.append(para_chunk.strip())
    return texts


def _hard_split_text(text: str, prefix: str, max_tokens: int) -> list[str]:
    """Split over-budget ``text`` into chunks that each fit ``max_tokens``.

    Each returned chunk carries ``prefix`` and stays within budget, splitting on
    word boundaries first and falling back to a character cut for any single
    word that alone exceeds the budget. Only reached when one paragraph is
    larger than the whole available window, a local small-window concern the
    section/paragraph passes above cannot resolve, so without this a single
    giant paragraph would be emitted as one over-window chunk.
    """
    pieces: list[str] = []
    current = prefix
    for word in text.split():
        candidate = f"{current}{word} "
        if estimate_tokens(candidate) <= max_tokens:
            current = candidate
            continue
        if current.strip() != prefix.strip():
            pieces.append(current)
            current = prefix
        word_chunk = f"{prefix}{word} "
        while estimate_tokens(word_chunk) > max_tokens:
            # A single word over budget: keep the prefix, take as many chars as
            # fit, and carry the rest forward.
            budget_chars = max(1, max_tokens * 4 - len(prefix))
            head, word = word[:budget_chars], word[budget_chars:]
            pieces.append(f"{prefix}{head}")
            word_chunk = f"{prefix}{word} "
        current = word_chunk
    if current.strip() != prefix.strip():
        pieces.append(current)
    return pieces
