"""Generate or verify candidate Distill 1.0 public contract snapshots."""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import sys
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
        "status": "candidate",
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
        "status": "candidate",
        "json_schema_dialect": JSON_SCHEMA_DIALECT,
        "tools": sorted(tools, key=lambda row: str(row["name"])),
        "resources": sorted(resources, key=lambda row: str(row["uri"])),
        "resource_templates": sorted(templates, key=lambda row: str(row["uriTemplate"])),
        "prompts": sorted(prompts, key=lambda row: str(row["name"])),
    }


async def snapshots() -> dict[Path, dict[str, object]]:
    """Return every public contract snapshot keyed by its tracked path."""
    return {
        CONTRACT_DIR / "cli-v1.json": cli_contract(),
        CONTRACT_DIR / "mcp-v1.json": await mcp_contract(),
    }


def _render(value: dict[str, object]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


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
    for path, value in (await snapshots()).items():
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
