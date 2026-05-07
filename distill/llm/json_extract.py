# pyright: strict
"""Robust JSON extraction from LLM responses.

Different models return JSON in different ways:
- Grok: clean JSON, no wrapping
- Gemma 4: may wrap in ```json code blocks, add preamble text
- Qwen3: may include thinking trace before JSON, or wrap in code blocks
- DeepSeek: may add explanation after JSON

This module handles all these cases by finding and extracting the JSON
object/array from arbitrary LLM output text.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["extract_json"]


def extract_json(text: str) -> dict[str, Any] | list[Any] | None:
    """Extract a JSON object or array from LLM response text.

    Tries multiple strategies in order:
    1. Direct parse (text is already valid JSON)
    2. Strip markdown code blocks (```json ... ```)
    3. Find first { or [ and parse from there
    4. Regex extraction of JSON-like content

    Returns the parsed JSON (dict or list), or None if extraction fails.
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # Strategy 1: Direct parse
    parsed = _try_parse(text)
    if parsed is not None:
        return parsed

    # Strategy 2: Strip markdown code blocks
    stripped = _strip_code_blocks(text)
    if stripped != text:
        parsed = _try_parse(stripped)
        if parsed is not None:
            return parsed

    # Strategy 3: Find first { or [ and parse from there
    parsed = _find_json_start(text)
    if parsed is not None:
        return parsed

    # Strategy 4: Try stripping everything before first { or [
    parsed = _find_json_start(stripped)
    if parsed is not None:
        return parsed

    logger.warning("Failed to extract JSON from LLM response (%d chars)", len(text))
    return None


def _try_parse(text: str) -> dict[str, Any] | list[Any] | None:
    """Try to parse text as JSON. Returns None on failure."""
    try:
        result: Any = json.loads(text)
        if isinstance(result, dict):
            return result  # type: ignore[reportUnknownVariableType]
        if isinstance(result, list):
            return result  # type: ignore[reportUnknownVariableType]
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _strip_code_blocks(text: str) -> str:
    """Strip markdown code block wrappers (```json ... ``` or ``` ... ```)."""
    # Match ```json\n...\n``` or ```\n...\n```
    pattern = r"```(?:json)?\s*\n(.*?)\n\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Simpler: just strip leading/trailing ``` lines
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    result = "\n".join(lines).strip()
    if result != text:
        return result

    return text


def _find_json_start(text: str) -> dict[str, Any] | list[Any] | None:
    """Find the first { or [ in text and try to parse from there."""
    # Find first { or [
    brace_idx = text.find("{")
    bracket_idx = text.find("[")

    if brace_idx < 0 and bracket_idx < 0:
        return None

    # Pick whichever comes first
    if brace_idx < 0:
        start = bracket_idx
    elif bracket_idx < 0:
        start = brace_idx
    else:
        start = min(brace_idx, bracket_idx)

    # Try parsing from that position to end
    candidate = text[start:]
    parsed = _try_parse(candidate)
    if parsed is not None:
        return parsed

    # Try finding the matching closing brace/bracket
    if text[start] == "{":
        end = _find_matching_brace(text, start)
    else:
        end = _find_matching_bracket(text, start)

    if end > start:
        candidate = text[start : end + 1]
        parsed = _try_parse(candidate)
        if parsed is not None:
            return parsed

    return None


def _find_matching_brace(text: str, start: int) -> int:
    """Find the matching } for a { at position start."""
    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == "\\":
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _find_matching_bracket(text: str, start: int) -> int:
    """Find the matching ] for a [ at position start."""
    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == "\\":
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i
    return -1
