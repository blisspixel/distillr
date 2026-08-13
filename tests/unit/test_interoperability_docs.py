"""Contracts keeping public interoperability guidance aligned with code."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

from distill.library.okf_v02 import OKF_VERSION

ROOT = Path(__file__).resolve().parents[2]
AGENT_PLUGINS_SCHEMA_SHA256 = "0a4aad95ce337878ad38802ebf0daa3fde76abe3f65400c86bcbb1ec0b3ab883"


def _portable_text_sha256(payload: bytes) -> str:
    """Hash text content after platform-independent newline normalization."""

    return hashlib.sha256(_normalize_newlines(payload)).hexdigest()


def _normalize_newlines(payload: bytes) -> bytes:
    """Return one LF baseline for portable text comparisons and fixtures."""

    return payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _load_distribution_generator() -> ModuleType:
    path = ROOT / "scripts/agent_skill_distributions.py"
    spec = importlib.util.spec_from_file_location("interop_distribution_generator", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_interoperability_baselines_match_code_and_immutable_schema() -> None:
    generator = _load_distribution_generator()
    schema_path = ROOT / "tests/fixtures/standards/agent-plugins-1.0.0-plugin.schema.json"

    assert generator.AGENT_PLUGINS_VERSION == "1.0.0"
    assert generator.AGENT_PLUGINS_SCHEMA == (
        "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    )
    assert OKF_VERSION == "0.2"
    schema_payload = schema_path.read_bytes()
    assert _portable_text_sha256(schema_payload) == AGENT_PLUGINS_SCHEMA_SHA256
    crlf_schema_payload = _normalize_newlines(schema_payload).replace(b"\n", b"\r\n")
    assert _portable_text_sha256(crlf_schema_payload) == AGENT_PLUGINS_SCHEMA_SHA256


def test_public_docs_state_exact_portable_boundaries() -> None:
    overview = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    standards = (ROOT / "docs/interoperability.md").read_text(encoding="utf-8")
    distribution = (ROOT / "docs/design/agent-skill-distribution.md").read_text(encoding="utf-8")
    okf_design = (ROOT / "docs/design/okf-loop-readiness.md").read_text(encoding="utf-8")

    assert "docs/interoperability.md" in overview
    assert "interoperability.md" in index
    assert "Last authoritative review: 2026-08-13" in standards
    assert "Agent Plugins 1.0.0" in standards
    assert "Working Draft" in standards
    assert "OKF 0.2" in standards
    assert "introduced OKF 0.1" in standards
    assert "distill-corpus-agent-plugin-<version>.zip" in standards
    assert "distill-corpus-plugin-<version>.zip" in standards
    assert "strict Agent Plugins 1.0.0" in distribution
    assert "../interoperability.md" in distribution
    assert "../interoperability.md" in okf_design
