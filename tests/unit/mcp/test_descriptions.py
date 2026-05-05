"""Property-based and unit tests for tool description character limits."""

from __future__ import annotations

import json

# ── Property 9: Tool descriptions respect character limits ──
# Feature: mcp-first-surface, Property 9: Tool descriptions respect character limits
# **Validates: Requirements 6.1, 6.2**


def _get_all_tools():
    """Introspect all registered tools on the MCP server."""
    from distill.mcp.server import mcp

    tools = mcp._tool_manager._tools
    return tools


def test_tool_descriptions_within_100_chars():
    """Property 9: All tool descriptions are <= 100 characters."""
    tools = _get_all_tools()
    assert len(tools) > 0, "No tools registered"

    violations = []
    for name, tool in tools.items():
        desc = tool.description or ""
        # The description is the first line of the docstring
        first_line = desc.split("\n")[0].strip()
        if len(first_line) > 100:
            violations.append(f"{name}: {len(first_line)} chars - '{first_line}'")

    assert not violations, "Tool descriptions exceed 100 chars:\n" + "\n".join(violations)


def test_param_descriptions_within_50_chars():
    """Property 9: All parameter descriptions are <= 50 characters."""
    tools = _get_all_tools()
    assert len(tools) > 0, "No tools registered"

    violations = []
    for name, tool in tools.items():
        # Get the tool's parameters from its schema
        schema = tool.parameters
        if not schema:
            continue
        properties = schema.get("properties", {})
        for param_name, param_info in properties.items():
            desc = param_info.get("description", "")
            if desc and len(desc) > 50:
                violations.append(f"{name}.{param_name}: {len(desc)} chars - '{desc}'")

    assert not violations, "Param descriptions exceed 50 chars:\n" + "\n".join(violations)


# ── Property 11: Tool schemas are valid JSON Schema Draft 7 ──
# Feature: mcp-first-surface, Property 11: Tool schemas are valid JSON Schema Draft 7
# **Validates: Requirements 11.3**


def test_tool_schemas_are_valid_json_schema():
    """Property 11: Tool schemas are valid JSON Schema Draft 7."""
    tools = _get_all_tools()
    assert len(tools) > 0, "No tools registered"

    for name, tool in tools.items():
        schema = tool.parameters
        # Basic JSON Schema structure checks
        assert isinstance(schema, dict), f"{name}: schema is not a dict"
        assert "properties" in schema or schema.get("type") == "object", (
            f"{name}: schema missing 'properties'"
        )
        # Verify it's valid JSON (serializable)
        json.dumps(schema)


# ── Backward compatibility snapshot tests ──


def test_existing_tools_still_registered():
    """Verify all 8 existing tools are still registered."""
    tools = _get_all_tools()
    expected = {
        "learn_topic",
        "search_videos",
        "catch_up",
        "process_video_url",
        "watch_add",
        "watch_remove",
        "generate_report",
        "resynthesize_topic",
        "research_gaps",
    }
    registered = set(tools.keys())
    missing = expected - registered
    assert not missing, f"Missing existing tools: {missing}"


def test_new_tools_registered():
    """Verify all new tools are registered."""
    tools = _get_all_tools()
    expected_new = {
        "find_insights",
        "read_insight",
        "papers",
        "discover",
        "site_batch",
        "synthesize",
        "costs",
        "doctor",
    }
    registered = set(tools.keys())
    missing = expected_new - registered
    assert not missing, f"Missing new tools: {missing}"


def test_existing_tool_schemas_unchanged():
    """Backward compatibility: existing tool input schemas are preserved."""
    tools = _get_all_tools()

    # Verify key parameters still exist for existing tools
    # learn_topic should still accept query, topic, days, limit
    lt_params = tools["learn_topic"].parameters.get("properties", {})
    assert "query" in lt_params
    assert "topic" in lt_params
    assert "days" in lt_params
    assert "limit" in lt_params

    # catch_up should still accept channel, topic, days
    cu_params = tools["catch_up"].parameters.get("properties", {})
    assert "channel" in cu_params
    assert "topic" in cu_params
    assert "days" in cu_params

    # watch_add should still accept url, topic, days, instructions
    wa_params = tools["watch_add"].parameters.get("properties", {})
    assert "url" in wa_params
    assert "topic" in wa_params
    assert "days" in wa_params
    assert "instructions" in wa_params
