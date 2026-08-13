"""Property-based and unit tests for tool description character limits."""

from __future__ import annotations

import json

import jsonschema

# ── Property 9: Tool descriptions respect character limits ──
# Feature: mcp-first-surface, Property 9: Tool descriptions respect character limits
# **Validates: Requirements 6.1, 6.2**


def _get_all_tools():
    """Introspect all registered tools through the public listing."""
    import asyncio

    from distill.mcp.server import mcp

    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


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
        schema = tool.input_schema
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


def test_tool_schemas_are_valid_json_schema_draft7():
    """Property 11: Tool schemas are valid JSON Schema Draft 7."""
    tools = _get_all_tools()
    assert len(tools) > 0, "No tools registered"

    for name, tool in tools.items():
        schema = tool.input_schema
        assert isinstance(schema, dict), f"{name}: schema is not a dict"

        # Verify it's valid JSON (serializable)
        serialized = json.dumps(schema)
        parsed = json.loads(serialized)

        # Validate the schema itself is a valid JSON Schema Draft 7
        # by checking it can be used as a schema (meta-validation)
        try:
            jsonschema.Draft7Validator.check_schema(parsed)
        except jsonschema.SchemaError as e:
            raise AssertionError(
                f"{name}: schema is not valid JSON Schema Draft 7: {e.message}"
            ) from None


def test_tool_schemas_have_required_structure():
    """Tool schemas have proper object type and properties."""
    tools = _get_all_tools()
    assert len(tools) > 0, "No tools registered"

    for name, tool in tools.items():
        schema = tool.input_schema
        assert isinstance(schema, dict), f"{name}: schema is not a dict"
        # All tool schemas should be object type with properties
        assert schema.get("type") == "object", f"{name}: schema type is not 'object'"
        assert "properties" in schema, f"{name}: schema missing 'properties'"


# ── Backward compatibility snapshot tests ──


def test_existing_tools_still_registered():
    """Verify all existing tools are still registered."""
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
    lt_params = tools["learn_topic"].input_schema.get("properties", {})
    assert "query" in lt_params
    assert "topic" in lt_params
    assert "days" in lt_params
    assert "limit" in lt_params

    # catch_up should still accept channel, topic, days
    cu_params = tools["catch_up"].input_schema.get("properties", {})
    assert "channel" in cu_params
    assert "topic" in cu_params
    assert "days" in cu_params

    # watch_add should still accept url, topic, days, instructions
    wa_params = tools["watch_add"].input_schema.get("properties", {})
    assert "url" in wa_params
    assert "topic" in wa_params
    assert "days" in wa_params
    assert "instructions" in wa_params

    # process_video_url should accept url, topic
    pv_params = tools["process_video_url"].input_schema.get("properties", {})
    assert "url" in pv_params
    assert "topic" in pv_params

    # watch_remove should accept name
    wr_params = tools["watch_remove"].input_schema.get("properties", {})
    assert "name" in wr_params

    # generate_report should accept topic, channel, profile
    gr_params = tools["generate_report"].input_schema.get("properties", {})
    assert "topic" in gr_params
    assert "channel" in gr_params
    assert "profile" in gr_params

    # resynthesize_topic should accept topic, channel
    rt_params = tools["resynthesize_topic"].input_schema.get("properties", {})
    assert "topic" in rt_params
    assert "channel" in rt_params

    # research_gaps should accept topic
    rg_params = tools["research_gaps"].input_schema.get("properties", {})
    assert "topic" in rg_params

    # search_videos should accept query, days, limit
    sv_params = tools["search_videos"].input_schema.get("properties", {})
    assert "query" in sv_params
    assert "days" in sv_params
    assert "limit" in sv_params


def _has_type(prop_schema: dict, expected_type: str) -> bool:
    """Check if a property schema includes the expected type (handles anyOf for optionals)."""
    if prop_schema.get("type") == expected_type:
        return True
    # Handle anyOf (e.g., int | None becomes anyOf: [{type: integer}, {type: null}])
    any_of = prop_schema.get("anyOf", [])
    return any(item.get("type") == expected_type for item in any_of)


def test_existing_tool_parameter_types_unchanged():
    """Backward compatibility: parameter types haven't changed."""
    tools = _get_all_tools()

    # learn_topic parameter types
    lt_props = tools["learn_topic"].input_schema.get("properties", {})
    assert _has_type(lt_props["query"], "string")
    assert _has_type(lt_props["days"], "integer")
    assert _has_type(lt_props["limit"], "integer")

    # catch_up parameter types (days is int | None)
    cu_props = tools["catch_up"].input_schema.get("properties", {})
    assert _has_type(cu_props["days"], "integer")

    # watch_add parameter types
    wa_props = tools["watch_add"].input_schema.get("properties", {})
    assert _has_type(wa_props["url"], "string")
    assert _has_type(wa_props["topic"], "string")
    assert _has_type(wa_props["days"], "integer")
    assert _has_type(wa_props["instructions"], "string")


def test_existing_tool_required_fields_unchanged():
    """Backward compatibility: required fields haven't changed."""
    tools = _get_all_tools()

    # learn_topic requires query
    lt_required = tools["learn_topic"].input_schema.get("required", [])
    assert "query" in lt_required

    # watch_add requires url
    wa_required = tools["watch_add"].input_schema.get("required", [])
    assert "url" in wa_required

    # process_video_url requires url
    pv_required = tools["process_video_url"].input_schema.get("required", [])
    assert "url" in pv_required

    # research_gaps requires topic
    rg_required = tools["research_gaps"].input_schema.get("required", [])
    assert "topic" in rg_required
