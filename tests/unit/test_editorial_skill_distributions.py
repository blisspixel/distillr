"""Portable editorial packages must work without the Distill runtime checkout."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

import pytest
import yaml
from jsonschema import Draft202012Validator

from scripts import editorial_skill_distributions as generator

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    shutil.copytree(ROOT / "skills/perspective-editorial", root / generator.SKILL)
    shutil.copytree(ROOT / "evals/perspective-editorial", root / generator.EVALS)
    shutil.copyfile(ROOT / "LICENSE", root / "LICENSE")
    return root


def test_tracked_plugin_matches_canonical_sources() -> None:
    assert generator.check_tracked(ROOT) == []


def test_build_is_standalone_reproducible_and_checksummed(source: Path, tmp_path: Path) -> None:
    private = source / "private"
    private.mkdir()
    (private / "perspective.toml").write_text("PRIVATE DO NOT DISTRIBUTE", encoding="utf-8")
    generator.write_tracked(source)
    first = generator.build_archives(source, tmp_path / "first")
    second = generator.build_archives(source, tmp_path / "second")
    assert {p.name: p.read_bytes() for p in first} == {p.name: p.read_bytes() for p in second}
    checksum = next(path for path in first if path.suffix == ".sha256")
    for line in checksum.read_text().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((checksum.parent / name).read_bytes()).hexdigest() == digest
    skill = next(path for path in first if path.suffix == ".skill")
    with zipfile.ZipFile(skill) as archive:
        archive.extractall(tmp_path / "installed")
        assert all(name.startswith("perspective-editorial/") for name in archive.namelist())
        assert all(b"PRIVATE DO NOT DISTRIBUTE" not in archive.read(n) for n in archive.namelist())
    installed = tmp_path / "installed/perspective-editorial"
    actual = {
        PurePosixPath(path.relative_to(installed).as_posix()): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    assert actual == generator.shared._skill_files(source, source_path=generator.SKILL)
    # All conditionally loaded references resolve inside the isolated installed skill.
    for relative in re.findall(
        r"`((?:references|assets)/[^`]+)`", (installed / "SKILL.md").read_text()
    ):
        assert (installed / relative).is_file()
    assert not (tmp_path / "installed/distill").exists()


def test_manifests_and_archive_roots(source: Path, tmp_path: Path) -> None:
    generator.write_tracked(source)
    paths = generator.build_archives(source, tmp_path / "archives")
    portable_path = next(path for path in paths if "-agent-plugin-" in path.name)
    native_path = next(
        path for path in paths if "-plugin-" in path.name and "-agent-plugin-" not in path.name
    )
    schema = json.loads(
        (ROOT / "tests/fixtures/standards/agent-plugins-1.0.0-plugin.schema.json").read_text()
    )
    with zipfile.ZipFile(portable_path) as portable, zipfile.ZipFile(native_path) as native:
        manifest = json.loads(portable.read("plugin.json"))
        Draft202012Validator(schema).validate(manifest)
        assert manifest["version"] == "0.1.0"
        assert "skills/perspective-editorial/SKILL.md" in portable.namelist()
        assert not any(name.startswith((".", "evals/")) for name in portable.namelist())
        for wrapper in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
            wrapped = json.loads(native.read(wrapper))
            assert wrapped["name"] == manifest["name"]
            assert wrapped["version"] == manifest["version"]
            assert not {"mcpServers", "hooks", "apps"}.intersection(wrapped)
        assert not {"mcp.json", ".mcp.json"}.intersection(native.namelist())


def test_skill_fits_companion_limits_and_private_profile_contract() -> None:
    files = generator.shared._skill_files(ROOT, source_path=generator.SKILL)
    assert len(files) - 1 <= 20
    assert len(files[PurePosixPath("SKILL.md")].splitlines()) < 500
    for path in files:
        assert all(re.fullmatch(r"[A-Za-z0-9_ .!\-]+", part) for part in path.parts)
        assert not any(part.startswith(".") for part in path.parts)
    profile = tomllib.loads(files[PurePosixPath("assets/perspective.example.toml")].decode())
    assert profile["author"]["company"] == ""
    assert profile["author"]["style_examples"] == []
    assert profile["workflow"]["external_paid_calls"] is False
    ui = yaml.safe_load(files[PurePosixPath("agents/openai.yaml")])
    assert 25 <= len(ui["interface"]["short_description"]) <= 64
    assert "$perspective-editorial" in ui["interface"]["default_prompt"]


def test_behavioral_cases_have_model_rubrics_and_no_tool_side_effects() -> None:
    cases = generator.shared._eval_files(ROOT, source_path=generator.EVALS)
    assert len(cases) >= 6
    for path, body in cases.items():
        case = yaml.safe_load(body)
        assert case["schema_version"] == "1.1"
        assert case["name"] == path.parent.name
        assert case["execution"]["allowed_tools"] == []
        assert case["execution"]["prompt"]
        assert case["graders"]
        assert all(item["type"] == "llm" and item["criteria"] for item in case["graders"])


def test_stale_and_extra_files_block_build_and_write_repairs_only_owned_tree(source: Path) -> None:
    generator.write_tracked(source)
    unrelated = source / "plugins/distill-corpus/keep.txt"
    unrelated.parent.mkdir()
    unrelated.write_text("keep", encoding="utf-8")
    generated = source / generator.PLUGIN
    (generated / "README.md").write_text("stale", encoding="utf-8")
    (generated / "extra.txt").write_text("extra", encoding="utf-8")
    (generated / "LICENSE").unlink()
    errors = generator.check_tracked(source)
    assert len(errors) == 3
    with pytest.raises(generator.shared.DistributionError, match="Run --write"):
        generator.build_archives(source, source / "output")
    generator.write_tracked(source)
    assert generator.check_tracked(source) == []
    assert unrelated.read_text() == "keep"


@pytest.mark.parametrize("name", [".env", "credentials.json", "secret.pem"])
def test_credentials_are_refused_in_skill_sources(source: Path, name: str) -> None:
    (source / generator.SKILL / name).write_text("do not pack", encoding="utf-8")
    with pytest.raises(generator.shared.DistributionError, match="Blocked file"):
        generator.write_tracked(source)


def test_hardlinks_are_refused_before_generated_content_is_changed(source: Path) -> None:
    generator.write_tracked(source)
    target = source / generator.PLUGIN / "README.md"
    os.link(target, source / "outside.txt")
    with pytest.raises(generator.shared.DistributionError, match="one-link"):
        generator.write_tracked(source)
    assert target.read_bytes() == (source / "outside.txt").read_bytes()


def test_generated_symlink_is_refused(source: Path) -> None:
    parent = source / "plugins"
    parent.mkdir()
    outside = source / "outside"
    outside.mkdir()
    try:
        (source / generator.PLUGIN).symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(generator.shared.DistributionError, match="linked"):
        generator.write_tracked(source)


def test_invalid_skill_version_is_refused(source: Path) -> None:
    skill = source / generator.SKILL / "SKILL.md"
    skill.write_text(skill.read_text().replace('version: "0.1.0"', 'version: "next"'))
    with pytest.raises(generator.shared.DistributionError, match="semantic versioning"):
        generator.write_tracked(source)


def test_shared_helpers_reject_traversal() -> None:
    for reader in (generator.shared._skill_files, generator.shared._eval_files):
        with pytest.raises(generator.shared.DistributionError, match="Unsafe distribution path"):
            reader(ROOT, source_path=PurePosixPath("../private"))


def test_cli_check() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.editorial_skill_distributions", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"current": True, "errors": []}
