"""Tests for the generated cross-client Agent Skill distributions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "agent_skill_distributions.py"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agent_skill_distributions", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = _load_generator()
VERSION = GENERATOR._project_version(ROOT)


def _minimal_root(tmp_path: Path, *, version: str = "1.2.3") -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "example"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "LICENSE").write_text("test license\n", encoding="utf-8")
    skill = root / "skills" / "distill-corpus"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: distill-corpus\ndescription: Test skill.\n---\n\n# Test\n",
        encoding="utf-8",
    )
    (skill / "references" / "worker.md").write_text("# Worker\n", encoding="utf-8")
    eval_case = root / "evals" / "distill-corpus" / "trigger"
    eval_case.mkdir(parents=True)
    (eval_case / "case.yaml").write_text(
        'schema_version: "1.1"\nname: trigger\nexecution:\n  prompt: Test\n'
        "graders:\n  - type: llm\n    name: fit\n    criteria: Test.\n",
        encoding="utf-8",
    )
    return root


def _archive_payloads(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_checked_in_distributions_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "distributions are current" in result.stdout


def test_generated_plugin_contains_exact_canonical_skill() -> None:
    expected = GENERATOR.expected_tracked_files(ROOT)
    canonical = GENERATOR._skill_files(ROOT)
    evals = GENERATOR._eval_files(ROOT)

    assert GENERATOR.check_tracked(ROOT) == []
    for relative, payload in canonical.items():
        generated = PurePosixPath("plugins/distill-corpus/skills/distill-corpus") / relative
        assert expected[generated] == payload
        bundled = PurePosixPath("distill/resources/agent-skills/distill-corpus") / relative
        assert expected[bundled] == payload
    for relative, payload in evals.items():
        generated = PurePosixPath("plugins/distill-corpus/evals") / relative
        assert expected[generated] == payload
    bundle_manifest = json.loads(
        expected[PurePosixPath("distill/resources/agent-skills/distill-corpus.manifest.json")]
    )
    assert bundle_manifest["version"] == VERSION
    assert bundle_manifest["bundle_sha256"] == GENERATOR._tree_digest(canonical)
    assert (
        f'"version": "{VERSION}"'.encode()
        in expected[PurePosixPath("plugins/distill-corpus/.codex-plugin/plugin.json")]
    )
    assert (
        b"$distill-corpus"
        in expected[PurePosixPath("plugins/distill-corpus/.codex-plugin/plugin.json")]
    )
    assert b'"name": "distillr"' in expected[PurePosixPath("gemini-extension.json")]


def test_write_repairs_drift_and_removes_unexpected_plugin_files(tmp_path: Path) -> None:
    root = _minimal_root(tmp_path)
    GENERATOR.write_tracked(root)
    assert GENERATOR.check_tracked(root) == []

    generated_skill = root / "plugins" / "distill-corpus" / "skills" / "distill-corpus"
    (generated_skill / "SKILL.md").write_text("stale\n", encoding="utf-8")
    (generated_skill / "unexpected.md").write_text("unexpected\n", encoding="utf-8")
    generated_bundle = root / "distill" / "resources" / "agent-skills"
    (generated_bundle / "unexpected.md").write_text("unexpected\n", encoding="utf-8")

    errors = GENERATOR.check_tracked(root)
    assert (
        "generated file is stale: plugins/distill-corpus/skills/distill-corpus/SKILL.md" in errors
    )
    assert (
        "unexpected generated plugin file: "
        "plugins/distill-corpus/skills/distill-corpus/unexpected.md"
    ) in errors
    assert (
        "unexpected generated bundled file: distill/resources/agent-skills/unexpected.md" in errors
    )

    GENERATOR.write_tracked(root)
    assert GENERATOR.check_tracked(root) == []
    assert not (generated_skill / "unexpected.md").exists()
    assert not (generated_bundle / "unexpected.md").exists()


def test_generator_rejects_invalid_version_and_credential_shaped_skill_file(
    tmp_path: Path,
) -> None:
    invalid_version_root = _minimal_root(tmp_path / "version", version="next")
    with pytest.raises(GENERATOR.DistributionError, match="semantic versioning"):
        GENERATOR.expected_tracked_files(invalid_version_root)

    unsafe_root = _minimal_root(tmp_path / "unsafe")
    (unsafe_root / "skills" / "distill-corpus" / "private.pem").write_text(
        "not a real key\n",
        encoding="utf-8",
    )
    with pytest.raises(GENERATOR.DistributionError, match="Blocked file"):
        GENERATOR.expected_tracked_files(unsafe_root)

    ownership_root = _minimal_root(tmp_path / "ownership")
    (ownership_root / "skills" / "distill-corpus" / ".distill-install.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    with pytest.raises(GENERATOR.DistributionError, match="Blocked file"):
        GENERATOR.expected_tracked_files(ownership_root)


def test_generator_rejects_hardlinked_skill_inputs(tmp_path: Path) -> None:
    root = _minimal_root(tmp_path)
    source = root / "skills" / "distill-corpus" / "references" / "worker.md"
    hardlink = source.with_name("linked.md")
    os.link(source, hardlink)
    with pytest.raises(GENERATOR.DistributionError, match="one-link regular files"):
        GENERATOR.expected_tracked_files(root)


def test_behavioral_eval_suite_has_positive_negative_and_model_judged_cases() -> None:
    cases = []
    for path in sorted((ROOT / "evals" / "distill-corpus").glob("*/case.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(value, dict)
        assert value["schema_version"] == "1.1"
        assert value["name"] == path.parent.name
        assert value["runs"] >= 1
        assert value["execution"]["allowed_tools"] == []
        assert value["execution"]["max_turns"] <= 4
        assert value["graders"]
        assert all(grader["type"] == "llm" for grader in value["graders"])
        assert all(grader["criteria"].strip() for grader in value["graders"])
        cases.append(value)

    assert len(cases) >= 6
    assert any("negative" in case["tags"] for case in cases)
    assert any("trigger" in case["tags"] and "negative" not in case["tags"] for case in cases)


def test_release_archives_are_deterministic_bounded_and_checksummed(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_paths = GENERATOR.build_archives(ROOT, first)
    second_paths = GENERATOR.build_archives(ROOT, second)
    first_by_name = {path.name: path for path in first_paths}
    second_by_name = {path.name: path for path in second_paths}

    assert first_by_name.keys() == second_by_name.keys()
    for name, first_path in first_by_name.items():
        assert first_path.read_bytes() == second_by_name[name].read_bytes()

    skill_path = first / f"distill-corpus-{VERSION}.skill"
    zip_path = first / f"distill-corpus-{VERSION}.zip"
    plugin_path = first / f"distill-corpus-plugin-{VERSION}.zip"
    assert skill_path.read_bytes() == zip_path.read_bytes()

    with zipfile.ZipFile(skill_path) as archive:
        names = archive.namelist()
        assert names
        assert len(names) == len(set(names))
        assert all(name.startswith("distill-corpus/") for name in names)
        assert "distill-corpus/SKILL.md" in names
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())

    plugin_payloads = _archive_payloads(plugin_path)
    assert "distill-corpus/.codex-plugin/plugin.json" in plugin_payloads
    assert "distill-corpus/.claude-plugin/plugin.json" in plugin_payloads
    assert "distill-corpus/gemini-extension.json" in plugin_payloads
    assert "distill-corpus/evals/billing-truth/case.yaml" in plugin_payloads
    assert (
        plugin_payloads["distill-corpus/skills/distill-corpus/SKILL.md"]
        == (ROOT / "skills" / "distill-corpus" / "SKILL.md").read_bytes()
    )

    checksum_path = first / f"distill-agent-distributions-{VERSION}.sha256"
    rows = {
        name: digest
        for digest, name in (
            line.split("  ", 1) for line in checksum_path.read_text(encoding="utf-8").splitlines()
        )
    }
    assert set(rows) == {
        f"distill-corpus-{VERSION}.skill",
        f"distill-corpus-{VERSION}.zip",
        f"distill-corpus-plugin-{VERSION}.zip",
    }
    for name, digest in rows.items():
        assert digest == hashlib.sha256((first / name).read_bytes()).hexdigest()
