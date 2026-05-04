"""Shared prompt rules and constants used across prompt domains.

Anti-hallucination, provenance, and formatting rules that are embedded
in multiple prompt templates. Centralised here for consistency.
"""

__all__ = [
    "ANTI_HALLUCINATION_RULES",
    "FORMATTING_RULES",
    "PROVENANCE_RULES",
]

ANTI_HALLUCINATION_RULES = (
    "NEVER invent statistics, studies, analyst reports, or data points not found in the "
    "research material. If the source material doesn't contain evidence for a claim, "
    "do NOT make it up. Omit it instead."
)

PROVENANCE_RULES = (
    "Use descriptive source attributions to PRIMARY sources: (per OpenAI blog, Oct 2025) "
    "or (per NVIDIA 10-K filing). Do NOT cite Wikipedia as a source; cite what Wikipedia "
    "references. For creator claims, attribute directly: (per NateBJones). "
    "Do NOT use numbered citations like [cite: 1]."
)

FORMATTING_RULES = (
    "Never use em-dashes or en-dashes. Use commas, semicolons, colons, or hyphens instead."
)
