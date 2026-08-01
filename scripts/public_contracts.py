"""Generate or verify candidate Distill 1.0 public contract snapshots."""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import sys
import types
import typing
from enum import Enum
from pathlib import Path
from typing import cast

from typer.main import get_command

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = ROOT / "docs" / "contracts"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _json_value(value: object) -> object:
    """Return a deterministic JSON representation of a Click default value."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if callable(value):
        return "<dynamic>"
    return str(value)


def _type_contract(parameter_type: object) -> dict[str, object]:
    """Capture stable validation details from a Click parameter type."""
    result: dict[str, object] = {
        "name": str(getattr(parameter_type, "name", parameter_type)),
    }
    for attribute in (
        "min",
        "max",
        "min_open",
        "max_open",
        "clamp",
        "exists",
        "file_okay",
        "dir_okay",
        "writable",
        "readable",
        "resolve_path",
        "allow_dash",
    ):
        if hasattr(parameter_type, attribute):
            result[attribute] = _json_value(getattr(parameter_type, attribute))
    choices = getattr(parameter_type, "choices", None)
    if choices is not None:
        result["choices"] = [str(choice) for choice in choices]
        result["case_sensitive"] = bool(getattr(parameter_type, "case_sensitive", True))
    return result


def _parameter_contract(parameter: object) -> dict[str, object]:
    """Capture the externally visible shape of one Click parameter."""
    kind = str(getattr(parameter, "param_type_name", ""))
    if kind not in {"argument", "option"}:
        raise TypeError(f"Unsupported CLI parameter kind: {kind or type(parameter).__name__}")
    contract: dict[str, object] = {
        "kind": kind,
        "name": str(getattr(parameter, "name", "")),
        "required": bool(getattr(parameter, "required", False)),
        "nargs": int(getattr(parameter, "nargs", 1)),
        "type": _type_contract(getattr(parameter, "type", "unknown")),
    }
    if kind == "option":
        contract["names"] = cast("list[str]", getattr(parameter, "opts", []))
        secondary_names = cast("list[str]", getattr(parameter, "secondary_opts", []))
        if secondary_names:
            contract["secondary_names"] = secondary_names
        contract["multiple"] = bool(getattr(parameter, "multiple", False))
        contract["count"] = bool(getattr(parameter, "count", False))
        contract["is_flag"] = bool(getattr(parameter, "is_flag", False))
        if contract["is_flag"]:
            contract["flag_value"] = _json_value(getattr(parameter, "flag_value", None))
    contract["default"] = _json_value(getattr(parameter, "default", None))
    return contract


def cli_contract() -> dict[str, object]:
    """Build the canonical CLI command, argument, and option inventory."""
    import distill.cli as cli

    root_command = get_command(cli.app)
    commands: list[dict[str, object]] = []

    def visit(command: object, path: tuple[str, ...]) -> None:
        parameters = cast("list[object]", getattr(command, "params", []))
        arguments: list[dict[str, object]] = []
        options: list[dict[str, object]] = []
        for parameter in parameters:
            row = _parameter_contract(parameter)
            if row["kind"] == "argument":
                row["position"] = len(arguments)
                arguments.append(row)
            else:
                options.append(row)
        children = cast("dict[str, object]", getattr(command, "commands", {}))
        command_row: dict[str, object] = {
            "path": " ".join(("distill", *path)),
            "parameters": arguments + sorted(options, key=lambda row: str(row["name"])),
        }
        if bool(getattr(command, "invoke_without_command", False)):
            command_row["invoke_without_command"] = True
        if bool(getattr(command, "no_args_is_help", False)):
            command_row["no_args_is_help"] = True
        if bool(getattr(command, "hidden", False)):
            command_row["hidden"] = True
        deprecated = getattr(command, "deprecated", None)
        if deprecated:
            command_row["deprecated"] = _json_value(deprecated)
        commands.append(command_row)
        for name, child in sorted(children.items()):
            visit(child, (*path, name))

    visit(root_command, ())
    return {
        "contract": "distill-cli.v1",
        "status": "freeze-ready",
        "commands": commands,
    }


def _without_prose(value: object) -> object:
    """Remove prose keys from non-schema MCP metadata."""
    if isinstance(value, dict):
        return {
            str(key): _without_prose(item)
            for key, item in sorted(value.items())
            if key not in {"description", "title"}
        }
    if isinstance(value, list):
        return [_without_prose(item) for item in value]
    return _json_value(value)


def _schema_without_prose(value: object) -> object:
    """Remove schema annotations without dropping property or definition names."""
    if not isinstance(value, dict):
        if isinstance(value, list):
            return [_schema_without_prose(item) for item in value]
        return _json_value(value)

    schema_maps = {"$defs", "definitions", "dependentSchemas", "patternProperties", "properties"}
    schema_lists = {"allOf", "anyOf", "oneOf", "prefixItems"}
    schema_values = {
        "additionalItems",
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
    result: dict[str, object] = {}
    for raw_key, item in sorted(value.items()):
        key = str(raw_key)
        if key in {"description", "title"}:
            continue
        if key in schema_maps and isinstance(item, dict):
            result[key] = {
                str(name): _schema_without_prose(child) for name, child in sorted(item.items())
            }
        elif key in schema_lists and isinstance(item, list):
            result[key] = [_schema_without_prose(child) for child in item]
        elif key in schema_values:
            result[key] = _schema_without_prose(item)
        else:
            result[key] = _json_value(item)
    return result


def _selected_fields(row: dict[str, object], names: tuple[str, ...]) -> dict[str, object]:
    return {
        name: (
            _schema_without_prose(row[name])
            if name in {"inputSchema", "outputSchema"}
            else _without_prose(row[name])
        )
        for name in names
        if name in row
    }


async def mcp_contract() -> dict[str, object]:
    """Build the canonical MCP tool, resource, template, and prompt inventory."""
    from distill.mcp.server import mcp

    tools = []
    for tool in await mcp.list_tools():
        row = cast("dict[str, object]", tool.model_dump(by_alias=True, exclude_none=True))
        tools.append(
            _selected_fields(
                row,
                ("name", "inputSchema", "outputSchema", "annotations", "execution"),
            )
        )

    resources = []
    for resource in await mcp.list_resources():
        row = cast("dict[str, object]", resource.model_dump(by_alias=True, exclude_none=True))
        resources.append(_selected_fields(row, ("uri", "name", "mimeType", "annotations")))

    templates = []
    for template in await mcp.list_resource_templates():
        row = cast("dict[str, object]", template.model_dump(by_alias=True, exclude_none=True))
        templates.append(_selected_fields(row, ("uriTemplate", "name", "mimeType", "annotations")))

    prompts = []
    for prompt in await mcp.list_prompts():
        row = cast("dict[str, object]", prompt.model_dump(by_alias=True, exclude_none=True))
        prompts.append(_selected_fields(row, ("name", "arguments")))

    return {
        "contract": "distill-mcp.v1",
        "status": "freeze-ready",
        "json_schema_dialect": JSON_SCHEMA_DIALECT,
        "tools": sorted(tools, key=lambda row: str(row["name"])),
        "resources": sorted(resources, key=lambda row: str(row["uri"])),
        "resource_templates": sorted(templates, key=lambda row: str(row["uriTemplate"])),
        "prompts": sorted(prompts, key=lambda row: str(row["name"])),
    }


def _data_type(value: object) -> str:
    """Return a language-neutral data type for persisted contract fields."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list | tuple):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def artifact_contract() -> dict[str, object]:
    """Build the canonical artifact-name and standard-frontmatter inventory."""
    from distill.library.paths import (
        ARTIFACT_SUFFIXES,
        LEGACY_ARTIFACT_NAMES,
        ProvenanceFields,
        artifact_candidate_paths,
        artifact_filename,
        base_frontmatter,
        dump_frontmatter,
        provenance_frontmatter,
    )

    artifact_types: dict[str, object] = {}
    for artifact_type, suffix in sorted(ARTIFACT_SUFFIXES.items()):
        legacy_filename = LEGACY_ARTIFACT_NAMES[artifact_type]
        extension = Path(legacy_filename).suffix.lstrip(".") or "md"
        filename = artifact_filename(
            "contract identity",
            artifact_type,
            extension=extension,
        )
        candidates = artifact_candidate_paths(
            Path("contract"),
            artifact_type,
            identity="contract identity",
            extension=extension,
        )
        artifact_types[artifact_type] = {
            "default_modern_pattern": artifact_filename("contract identity", artifact_type).replace(
                "contract_identity", "{identity}", 1
            ),
            "extension": extension,
            "legacy_filename": legacy_filename,
            "modern_pattern": filename.replace("contract_identity", "{identity}", 1),
            "reader_patterns": [
                candidate.name.replace("contract_identity", "{identity}", 1)
                for candidate in candidates
            ],
            "suffix": suffix,
        }

    provenance = ProvenanceFields(
        model="provider/model",
        model_version="model-version",
        temperature=0.0,
        prompt_id="prompt.v1",
    )
    standard_frontmatter = base_frontmatter(
        artifact_type="insights",
        title="Contract title",
        topic="contract-topic",
        source="contract-source",
        source_id="contract-id",
        url="https://example.com/source",
        date="2026-07-10",
        authors=["Example Author"],
        tags=["distill/contract-topic"],
        synthesis_scope="single-source",
        provenance=provenance,
    )
    provenance_fields = provenance_frontmatter(provenance)
    serialized_example = dump_frontmatter(
        {
            "string": "contract value",
            "boolean_true": True,
            "boolean_false": False,
            "integer": 1,
            "number": 1.5,
            "array": ["alpha", "beta"],
            "object": {"alpha": 1},
            "empty_string": "",
            "empty_array": [],
            "empty_object": {},
            "none": None,
        }
    )

    return {
        "contract": "distill-artifacts.v1",
        "status": "freeze-ready",
        "artifact_types": artifact_types,
        "frontmatter": {
            "base_fields": sorted(set(standard_frontmatter) - set(provenance_fields)),
            "field_types": {
                name: _data_type(value) for name, value in sorted(standard_frontmatter.items())
            },
            "provenance_fields": sorted(provenance_fields),
            "serialization_example": serialized_example,
        },
    }


class _TypedDictMetadata(typing.Protocol):
    __required_keys__: frozenset[str]


def _persisted_schema(annotation: object) -> dict[str, object]:
    """Translate the persisted TypedDict subset into Draft 2020-12 schema."""
    if typing.is_typeddict(annotation):
        hints = typing.get_type_hints(annotation)
        required = cast("_TypedDictMetadata", annotation).__required_keys__
        return {
            "type": "object",
            "properties": {name: _persisted_schema(value) for name, value in sorted(hints.items())},
            "required": sorted(required),
            "additionalProperties": False,
        }

    origin = typing.get_origin(annotation)
    arguments = typing.get_args(annotation)
    if origin is list:
        return {"type": "array", "items": _persisted_schema(arguments[0])}
    if origin is dict:
        return {"type": "object", "additionalProperties": _persisted_schema(arguments[1])}
    if origin in {types.UnionType, typing.Union}:
        return {"anyOf": [_persisted_schema(value) for value in arguments]}

    scalar_types = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        type(None): "null",
    }
    if annotation in scalar_types:
        return {"type": scalar_types[annotation]}
    if annotation is typing.Any:
        return {}
    raise TypeError(f"Unsupported persisted contract annotation: {annotation!r}")


def state_contract() -> dict[str, object]:
    """Build normalized library and channel-state persistence contracts."""
    from distill.library.state import (
        ChannelStateData,
        LibraryData,
        _parse_channel_state,
        _parse_library,
    )

    legacy_library = {
        "topics": {
            "contract-topic": {
                "channels": [{"url": "https://example.com/channel", "name": "Contract Channel"}]
            }
        },
        "watchlist": [{"url": "https://example.com/watch", "name": "Legacy Watch"}],
        "topic_watchlist": [{"name": "Legacy Topic Watch", "query": "contract query"}],
    }
    legacy_channel_state = {
        "processed_videos": {
            "video-id": {
                "title": "Contract Video",
                "upload_date": "20260710",
                "processed_at": "2026-07-10T00:00:00",
            }
        },
        "last_refresh": "2026-07-10T00:00:00",
    }
    explicit_library = {
        "topics": {},
        "watchlist": [
            {
                "url": "https://example.com/explicit-watch",
                "name": "Explicit Watch",
                "topic": "explicit-topic",
                "added_at": "2026-07-10T00:00:00",
                "instructions": "Track releases",
                "days": 21,
            }
        ],
        "topic_watchlist": [
            {
                "name": "Explicit Topic Watch",
                "query": "explicit query",
                "topic": "explicit-topic",
                "cadence": "daily",
                "days": 30,
                "limit": 20,
                "sort": "relevance",
                "channel_cap": 5,
                "ranking_mode": "quality",
                "added_at": "2026-07-10T00:00:00",
                "last_run_at": "2026-07-10T01:00:00",
                "report": True,
                "max_run_cost": 2,
                "monthly_budget": 3.5,
                "paused": True,
            }
        ],
    }
    explicit_channel_state = {
        "processed_videos": {
            "explicit-video": {
                "title": "Explicit Video",
                "upload_date": "20260710",
                "processed_at": "2026-07-10T01:00:00",
                "analysis_mode": "scan",
            }
        },
        "last_refresh": None,
    }

    return {
        "contract": "distill-state.v1",
        "json_schema_dialect": JSON_SCHEMA_DIALECT,
        "status": "freeze-ready",
        "documents": {
            "channel_state": {
                "normalized_schema": _persisted_schema(ChannelStateData),
                "compatibility_cases": [
                    {"name": "empty", "input": {}, "normalized": _parse_channel_state({})},
                    {
                        "name": "legacy_missing_analysis_mode",
                        "input": legacy_channel_state,
                        "normalized": _parse_channel_state(legacy_channel_state),
                    },
                    {
                        "name": "missing_scalar_fields",
                        "input": {"processed_videos": {"missing-fields": {}}},
                        "normalized": _parse_channel_state(
                            {"processed_videos": {"missing-fields": {}}}
                        ),
                    },
                    {
                        "name": "explicit_fields",
                        "input": explicit_channel_state,
                        "normalized": _parse_channel_state(explicit_channel_state),
                    },
                ],
            },
            "library_index": {
                "normalized_schema": _persisted_schema(LibraryData),
                "compatibility_cases": [
                    {"name": "empty", "input": {}, "normalized": _parse_library({})},
                    {
                        "name": "legacy_missing_optional_fields",
                        "input": legacy_library,
                        "normalized": _parse_library(legacy_library),
                    },
                    {
                        "name": "missing_scalar_fields",
                        "input": {
                            "topics": {
                                "missing-channels": {},
                                "missing-fields": {"channels": [{}]},
                            },
                            "watchlist": [{}],
                            "topic_watchlist": [{}],
                        },
                        "normalized": _parse_library(
                            {
                                "topics": {
                                    "missing-channels": {},
                                    "missing-fields": {"channels": [{}]},
                                },
                                "watchlist": [{}],
                                "topic_watchlist": [{}],
                            }
                        ),
                    },
                    {
                        "name": "explicit_fields_and_numeric_types",
                        "input": explicit_library,
                        "normalized": _parse_library(explicit_library),
                    },
                ],
            },
        },
    }


def config_contract() -> dict[str, object]:
    """Build the core DistillConfig and configuration-owned path contract."""
    from distill.config import DistillConfig, _default_library_dir

    schema = cast("dict[str, object]", _schema_without_prose(DistillConfig.model_json_schema()))
    properties = cast("dict[str, dict[str, object]]", schema["properties"])
    properties["distill_output_dir"]["default"] = "<topology-dependent; see default cases>"

    normalization_input = {
        "distill_cost_mode": " NO-METERED ",
        "distill_cost_warning_daily_usd": "12.5",
        "distill_cost_warning_spike_multiplier": 3,
        "distill_cost_warning_run_spike_min_usd": "0",
        "distill_cost_workflow_budgets": {"report": 5, "discover": 2.5},
    }
    normalization_output = {
        "distill_cost_mode": DistillConfig._normalize_distill_cost_mode(
            normalization_input["distill_cost_mode"]
        ),
        "distill_cost_warning_daily_usd": DistillConfig._normalize_cost_warning_daily_usd(
            normalization_input["distill_cost_warning_daily_usd"]
        ),
        "distill_cost_warning_run_spike_min_usd": (
            DistillConfig._normalize_cost_warning_run_spike_min_usd(
                normalization_input["distill_cost_warning_run_spike_min_usd"]
            )
        ),
        "distill_cost_warning_spike_multiplier": (
            DistillConfig._normalize_cost_warning_spike_multiplier(
                normalization_input["distill_cost_warning_spike_multiplier"]
            )
        ),
        "distill_cost_workflow_budgets": (
            DistillConfig._normalize_distill_cost_workflow_budgets(
                normalization_input["distill_cost_workflow_budgets"]
            )
        ),
    }

    def rejection(
        field: str,
        value: object,
        validator: typing.Callable[[object], object],
    ) -> dict[str, object]:
        try:
            validator(value)
        except ValueError:
            return {"field": field, "input": value, "rejected": True}
        raise AssertionError(f"contract rejection case unexpectedly accepted: {field}")

    rejection_cases = [
        rejection("distill_cost_mode", "free", DistillConfig._normalize_distill_cost_mode),
        rejection(
            "distill_cost_warning_daily_usd",
            0,
            DistillConfig._normalize_cost_warning_daily_usd,
        ),
        rejection(
            "distill_cost_warning_daily_usd",
            True,
            DistillConfig._normalize_cost_warning_daily_usd,
        ),
        rejection(
            "distill_cost_warning_daily_usd",
            "inf",
            DistillConfig._normalize_cost_warning_daily_usd,
        ),
        rejection(
            "distill_cost_warning_spike_multiplier",
            1,
            DistillConfig._normalize_cost_warning_spike_multiplier,
        ),
        rejection(
            "distill_cost_warning_run_spike_min_usd",
            -1,
            DistillConfig._normalize_cost_warning_run_spike_min_usd,
        ),
        rejection(
            "distill_cost_workflow_budgets",
            "bad key=2",
            DistillConfig._normalize_distill_cost_workflow_budgets,
        ),
        rejection(
            "distill_cost_workflow_budgets",
            "report=0",
            DistillConfig._normalize_distill_cost_workflow_budgets,
        ),
    ]

    contract_root = ROOT / "__contract_library__"
    path_config = DistillConfig.model_construct(distill_output_dir=contract_root)

    def relative(path: Path) -> str:
        return path.relative_to(contract_root).as_posix()

    path_examples = {
        "topics": relative(path_config.topics_dir()),
        "topic": relative(path_config.topic_dir("Contract Topic")),
        "topic_traversal_input": relative(path_config.topic_dir("../Escape")),
        "channel": relative(path_config.channel_dir("Contract Topic", "Contract Channel")),
        "videos": relative(path_config.videos_dir("Contract Topic", "Contract Channel")),
        "video": relative(path_config.video_dir("Contract Topic", "Contract Channel", "video-id")),
        "video_slug": relative(
            path_config.video_dir_slug(
                "Contract Topic", "Contract Channel", "Contract Video", "video-id"
            )
        ),
        "sites": relative(path_config.sites_dir("Contract Topic")),
        "site": relative(path_config.site_dir("Contract Topic", "Example Site")),
        "site_pages": relative(path_config.site_pages_dir("Contract Topic", "Example Site")),
        "site_page": relative(
            path_config.site_page_dir("Contract Topic", "Example Site", "Example Page", "page-id")
        ),
        "site_page_without_id": relative(
            path_config.site_page_dir("Contract Topic", "Example Site", "Example Page")
        ),
        "papers": relative(path_config.papers_dir("Contract Topic")),
        "paper": relative(path_config.paper_dir("Contract Topic", "Example Paper", "paper-id")),
        "paper_without_id": relative(path_config.paper_dir("Contract Topic", "Example Paper")),
    }
    relative_config = DistillConfig.model_construct(distill_output_dir=Path("relative-library"))

    settings_config = DistillConfig.model_config
    env_prefix = str(settings_config.get("env_prefix") or "")
    loader_keys = (
        "case_sensitive",
        "enable_decoding",
        "env_file",
        "env_file_encoding",
        "env_ignore_empty",
        "env_nested_delimiter",
        "env_nested_max_split",
        "env_parse_enums",
        "env_parse_none_str",
        "env_prefix",
        "env_prefix_target",
        "extra",
        "nested_model_default_partial_update",
        "secrets_dir",
    )

    return {
        "contract": "distill-core-config.v1",
        "status": "freeze-ready",
        "schema": schema,
        "environment": {
            "loader_policy": {key: _json_value(settings_config.get(key)) for key in loader_keys},
            "variables": {
                name: {
                    "canonical_name": f"{env_prefix}{name}".upper(),
                    "validation_alias": (
                        None if field.validation_alias is None else str(field.validation_alias)
                    ),
                }
                for name, field in sorted(DistillConfig.model_fields.items())
            },
        },
        "library_default_topology": {
            "installed_relative_to_home": _default_library_dir(ROOT / "site-packages" / "distill")
            .relative_to(Path.home())
            .as_posix(),
            "relative_input_relative_to_root": relative_config.library_dir.relative_to(
                ROOT
            ).as_posix(),
            "source_checkout_relative_to_root": _default_library_dir(ROOT / "distill")
            .relative_to(ROOT)
            .as_posix(),
        },
        "normalization_cases": [
            {
                "name": "cost_policy_and_budget_mapping",
                "input": normalization_input,
                "normalized": normalization_output,
            },
            {
                "name": "workflow_budget_string",
                "input": "report=5,discover=2.5",
                "normalized": DistillConfig._normalize_distill_cost_workflow_budgets(
                    "report=5,discover=2.5"
                ),
            },
        ],
        "path_examples": path_examples,
        "rejection_cases": rejection_cases,
    }


async def snapshots() -> dict[Path, dict[str, object]]:
    """Return every public contract snapshot keyed by its tracked path."""
    return {
        CONTRACT_DIR / "artifacts-v1.json": artifact_contract(),
        CONTRACT_DIR / "cli-v1.json": cli_contract(),
        CONTRACT_DIR / "config-v1.json": config_contract(),
        CONTRACT_DIR / "mcp-v1.json": await mcp_contract(),
        CONTRACT_DIR / "state-v1.json": state_contract(),
    }


def _render(value: dict[str, object]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _emit(message: str) -> None:
    sys.stdout.write(message + "\n")


async def _write() -> int:
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    for path, value in (await snapshots()).items():
        path.write_text(_render(value), encoding="utf-8")
        _emit(f"wrote {path.relative_to(ROOT)}")
    return 0


async def _check() -> int:
    mismatches = 0
    generated = await snapshots()
    expected_paths = set(generated)
    tracked_paths = set(CONTRACT_DIR.glob("*-v1.json"))
    for path in sorted(tracked_paths - expected_paths):
        _emit(f"unexpected contract snapshot: {path.relative_to(ROOT)}")
        mismatches += 1
    for path, value in generated.items():
        actual = _render(value)
        if not path.exists():
            _emit(f"missing {path.relative_to(ROOT)}; run with --write")
            mismatches += 1
            continue
        expected = path.read_text(encoding="utf-8")
        if expected == actual:
            continue
        _emit(f"contract mismatch: {path.relative_to(ROOT)}")
        _emit(
            "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    fromfile="tracked",
                    tofile="runtime",
                )
            )
        )
        mismatches += 1
    return 1 if mismatches else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify tracked snapshots")
    mode.add_argument("--write", action="store_true", help="replace snapshots from runtime")
    args = parser.parse_args()
    return asyncio.run(_write() if args.write else _check())


if __name__ == "__main__":
    raise SystemExit(main())
