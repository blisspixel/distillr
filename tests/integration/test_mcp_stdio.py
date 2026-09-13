"""Exercise the installed MCP runtime across modern and legacy stdio clients."""

from __future__ import annotations

import asyncio
import json
import sys
from importlib.metadata import version
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from distill.config import DistillConfig
from distill.library import Library


@pytest.mark.parametrize("mode", ["auto", "2026-07-28", "legacy"])
def test_stdio_discovery_fresh_reads_and_write_refusal(tmp_path, mode):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    library = Library(config)
    library.add_channel("first", "https://www.youtube.com/@First", "First")
    boundaries = Path(__file__).resolve().parents[1] / "conftest.py"
    bootstrap = f"""
import os
import runpy
import socket
boundaries = runpy.run_path({str(boundaries)!r})
for name in boundaries["_CLOUD_CREDENTIAL_ENV_VARS"]:
    os.environ[name] = boundaries["_INERT_TEST_CREDENTIAL"]
for operation in ("connect", "connect_ex"):
    original = getattr(socket.socket, operation)
    guarded = boundaries["_guarded_socket_method"](original, operation)
    setattr(socket.socket, operation, guarded)
from distill.mcp.server import main
main()
"""
    server = StdioServerParameters(
        command=sys.executable,
        args=["-c", bootstrap],
        cwd=tmp_path,
        env={
            "DISTILL_OUTPUT_DIR": str(config.distill_output_dir),
            "DISTILL_MCP_READ_ONLY": "1",
            "DISTILL_COST_MODE": "no-metered",
            "PYTHON_DOTENV_DISABLED": "1",
        },
    )

    async def exercise():
        async with Client(server, mode=mode, read_timeout_seconds=20) as client:
            assert client.protocol_version == ("2025-11-25" if mode == "legacy" else "2026-07-28")
            tools = await client.list_tools()
            names = [tool.name for tool in tools.tools]
            assert names == sorted(names)
            assert {"list_topics", "read_insight", "synthesize"} <= set(names)
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
            prompts = await client.list_prompts()
            for keys in (
                [str(resource.uri) for resource in resources.resources],
                [template.uri_template for template in templates.resource_templates],
                [prompt.name for prompt in prompts.prompts],
            ):
                assert keys
                assert keys == sorted(keys)
            if mode != "legacy":
                identity = tools.meta["io.modelcontextprotocol/serverInfo"]
                assert identity["name"] == "Distill"
                assert identity["version"] == version("distillr")
                for listing in (tools, resources, templates, prompts):
                    assert listing.ttl_ms == 3_600_000
                    assert listing.cache_scope == "private"
                discovered = await client.session.send_discover("2026-07-28")
                assert discovered["_meta"]["io.modelcontextprotocol/serverInfo"]["version"] == (
                    version("distillr")
                )
                assert "2026-07-28" in discovered["supportedVersions"]
                capabilities = discovered["capabilities"]
            else:
                assert client.server_info.version == version("distillr")
                capabilities = client.server_capabilities.model_dump(mode="json")
            assert "io.modelcontextprotocol/tasks" not in json.dumps(capabilities)

            before = await client.read_resource("distill://topics")
            if mode != "legacy":
                assert before.ttl_ms == 0
                assert before.cache_scope == "private"
            before_text = before.contents[0].text
            assert "first" in before_text
            assert "second" not in before_text
            library.add_channel("second", "https://www.youtube.com/@Second", "Second")
            after = await client.read_resource("distill://topics")
            if mode != "legacy":
                assert after.ttl_ms == 0
                assert after.cache_scope == "private"
            assert "second" in after.contents[0].text

            refused = await client.call_tool("synthesize", {"topic": "first", "force": True})
            result = json.loads(refused.content[0].text)
            assert result["status"] == "read_only"
            assert result["phase"] == "gate.read_only"

    asyncio.run(exercise())
