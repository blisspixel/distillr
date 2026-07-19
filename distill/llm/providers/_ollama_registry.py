# pyright: strict
"""Bounded validation for Ollama metadata responses."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, cast

from distill.llm._parsing import parse_ascii_uint


@dataclass(frozen=True)
class TagRegistryLimits:
    """Structural limits for one ``/api/tags`` response."""

    models: int
    model_fields: int
    details_fields: int
    list_items: int
    field_name_chars: int
    model_name_chars: int
    string_chars: int


def bounded_context_window(value: object, *, maximum: int) -> int | None:
    """Return a positive, bounded integral context window when valid."""

    if isinstance(value, str):
        parsed = parse_ascii_uint(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        parsed = value
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        parsed = int(value)
    else:
        parsed = None
    return parsed if parsed is not None and 1 <= parsed <= maximum else None


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON constant {value}")


def _bounded_scalar(value: object, *, field: str, limits: TagRegistryLimits) -> object:
    if isinstance(value, str):
        if len(value) > limits.string_chars:
            raise ValueError(f"Ollama model field {field!r} exceeds its string limit")
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f"Ollama model field {field!r} has an invalid value shape")


def _bounded_details(value: object, *, limits: TagRegistryLimits) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Ollama model details must be an object")
    details = cast(dict[object, object], value)
    if len(details) > limits.details_fields:
        raise ValueError("Ollama model details field count exceeds its limit")
    bounded: dict[str, Any] = {}
    for raw_key, raw_value in details.items():
        if not isinstance(raw_key, str) or len(raw_key) > limits.field_name_chars:
            raise ValueError("Ollama model details has an invalid field name")
        if isinstance(raw_value, list):
            values = cast(list[object], raw_value)
            if len(values) > limits.list_items:
                raise ValueError("Ollama model details list exceeds its item limit")
            bounded[raw_key] = [
                _bounded_scalar(item, field=f"details.{raw_key}", limits=limits) for item in values
            ]
        else:
            bounded[raw_key] = _bounded_scalar(
                raw_value,
                field=f"details.{raw_key}",
                limits=limits,
            )
    return bounded


def _bounded_model(value: object, *, limits: TagRegistryLimits) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Ollama models list contains a non-model object")
    model = cast(dict[object, object], value)
    if len(model) > limits.model_fields:
        raise ValueError("Ollama model field count exceeds its limit")
    name = model.get("name")
    if not isinstance(name, str) or not name or len(name) > limits.model_name_chars:
        raise ValueError("Ollama model object has an invalid name field")
    bounded: dict[str, Any] = {}
    for raw_key, raw_value in model.items():
        if not isinstance(raw_key, str) or len(raw_key) > limits.field_name_chars:
            raise ValueError("Ollama model object has an invalid field name")
        if raw_key == "details":
            bounded[raw_key] = _bounded_details(raw_value, limits=limits)
        else:
            bounded[raw_key] = _bounded_scalar(raw_value, field=raw_key, limits=limits)
    return bounded


def parse_tags_response(raw: bytes, *, limits: TagRegistryLimits) -> list[dict[str, Any]]:
    """Parse one strict, bounded Ollama model registry document."""

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Ollama model registry is not valid UTF-8") from exc
    try:
        data = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, MemoryError, RecursionError, ValueError) as exc:
        raise ValueError("Ollama model registry is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Ollama model registry must be an object")
    payload = cast(dict[object, object], data)
    if set(payload) != {"models"} or not isinstance(payload.get("models"), list):
        raise ValueError("Ollama model registry must contain only a models list")
    models = cast(list[object], payload["models"])
    if len(models) > limits.models:
        raise ValueError("Ollama model registry model count exceeds its limit")
    return [_bounded_model(model, limits=limits) for model in models]
