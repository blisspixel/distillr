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
        section_tokens = estimate_tokens(section_text)

        if section_tokens <= available_tokens:
            chunks.append(
                Chunk(
                    text=section_text.strip(),
                    heading_context=current_heading,
                    index=len(chunks),
                    total_chunks=0,  # will be updated
                )
            )
        else:
            # Section too large — split at paragraph boundaries
            paragraphs = _split_into_paragraphs(body)
            para_chunk = heading + "\n" if heading else ""

            for para in paragraphs:
                candidate = para_chunk + para + "\n\n"
                if estimate_tokens(candidate) > available_tokens and para_chunk.strip():
                    # Flush current chunk
                    chunks.append(
                        Chunk(
                            text=para_chunk.strip(),
                            heading_context=current_heading,
                            index=len(chunks),
                            total_chunks=0,
                        )
                    )
                    para_chunk = f"[continued from: {current_heading}]\n{para}\n\n"
                else:
                    para_chunk = candidate

            if para_chunk.strip():
                chunks.append(
                    Chunk(
                        text=para_chunk.strip(),
                        heading_context=current_heading,
                        index=len(chunks),
                        total_chunks=0,
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
            # New heading — flush previous section
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
