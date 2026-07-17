"""Tests for the integrity-checked Agent Skill wheel resource."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from unittest.mock import MagicMock

import pytest

from distill.agent_skills import bundle as bundle_module
from distill.agent_skills.bundle import SkillBundleError, load_bundled_skill, tree_digest

ROOT = Path(__file__).resolve().parents[3]


def _write_manifest(
    root: Path,
    manifest: Path,
    *,
    version: str = "1.2.3",
    bundle_hash: str | None = None,
) -> None:
    files = {
        PurePosixPath(path.relative_to(root).as_posix()): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    value = {
        "schema_version": "distill-agent-skill-bundle.v1",
        "name": "distill-corpus",
        "version": version,
        "bundle_sha256": bundle_hash or tree_digest(files),
        "files": {
            relative.as_posix(): {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for relative, payload in files.items()
        },
    }
    manifest.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "distill-corpus"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: distill-corpus\ndescription: Test.\n---\n",
        encoding="utf-8",
    )
    (root / "references" / "worker.md").write_text("# Worker\n", encoding="utf-8")
    manifest = tmp_path / "distill-corpus.manifest.json"
    _write_manifest(root, manifest)
    return root, manifest


def test_bundled_skill_matches_the_canonical_source() -> None:
    bundle = load_bundled_skill()
    source = ROOT / "skills" / "distill-corpus"
    expected = {
        PurePosixPath(path.relative_to(source).as_posix()): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }

    assert bundle.name == "distill-corpus"
    packaged_manifest = json.loads(
        (
            ROOT / "distill" / "resources" / "agent-skills" / "distill-corpus.manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert bundle.version == packaged_manifest["version"]
    assert bundle.files == expected
    assert bundle.bundle_sha256 == tree_digest(expected)
    assert bundle.total_bytes == sum(map(len, expected.values()))
    assert bundle.as_dict()["files"] == len(expected)
    assert (
        bundle.file_hashes()["SKILL.md"]
        == hashlib.sha256(expected[PurePosixPath("SKILL.md")]).hexdigest()
    )
    assert not hasattr(bundle.files, "__setitem__")


def test_skill_bundle_copies_the_input_mapping() -> None:
    files = {PurePosixPath("SKILL.md"): b"content"}
    bundle = bundle_module.SkillBundle(
        name="distill-corpus",
        version="1.0.0",
        bundle_sha256=tree_digest(files),
        files=files,
    )
    files.clear()
    assert bundle.files == {PurePosixPath("SKILL.md"): b"content"}


def test_custom_bundle_loads_and_detects_content_or_inventory_drift(tmp_path: Path) -> None:
    root, manifest = _fixture(tmp_path)
    loaded = bundle_module._load_bundle(root, manifest)
    assert loaded.version == "1.2.3"

    (root / "SKILL.md").write_text("changed", encoding="utf-8")
    with pytest.raises(SkillBundleError, match="integrity verification"):
        bundle_module._load_bundle(root, manifest)

    root, manifest = _fixture(tmp_path / "inventory")
    (root / "unexpected.md").write_text("extra", encoding="utf-8")
    with pytest.raises(SkillBundleError, match="inventory"):
        bundle_module._load_bundle(root, manifest)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(schema_version="wrong"), "identity"),
        (lambda value: value.update(version="next"), "version"),
        (lambda value: value.update(bundle_sha256="bad"), "digest"),
        (lambda value: value.update(files={}), "files"),
    ],
)
def test_manifest_contract_rejects_invalid_fields(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    root, manifest = _fixture(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    mutation(value)
    manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(SkillBundleError, match=message):
        bundle_module._load_bundle(root, manifest)


def test_manifest_rejects_invalid_json_and_non_object(tmp_path: Path) -> None:
    root, manifest = _fixture(tmp_path)
    manifest.write_text("{", encoding="utf-8")
    with pytest.raises(SkillBundleError, match="manifest is invalid"):
        bundle_module._load_bundle(root, manifest)

    manifest.write_text("[]", encoding="utf-8")
    with pytest.raises(SkillBundleError, match="must be an object"):
        bundle_module._load_bundle(root, manifest)


def test_manifest_rejects_bad_file_metadata_and_tree_digest(tmp_path: Path) -> None:
    root, manifest = _fixture(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["files"]["SKILL.md"]["bytes"] = True
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(SkillBundleError, match="metadata"):
        bundle_module._load_bundle(root, manifest)

    _write_manifest(root, manifest, bundle_hash="0" * 64)
    with pytest.raises(SkillBundleError, match="tree digest"):
        bundle_module._load_bundle(root, manifest)


def test_bundle_requires_manifest_directory_and_skill_entrypoint(tmp_path: Path) -> None:
    root, manifest = _fixture(tmp_path)
    with pytest.raises(SkillBundleError, match="manifest is missing"):
        bundle_module._load_bundle(root, tmp_path / "missing.json")
    with pytest.raises(SkillBundleError, match="directory is missing"):
        bundle_module._load_bundle(tmp_path / "missing", manifest)

    (root / "SKILL.md").unlink()
    _write_manifest(root, manifest)
    with pytest.raises(SkillBundleError, match=r"missing SKILL\.md"):
        bundle_module._load_bundle(root, manifest)

    root, manifest = _fixture(tmp_path / "ownership")
    (root / ".distill-install.json").write_text("{}", encoding="utf-8")
    _write_manifest(root, manifest)
    with pytest.raises(SkillBundleError, match="ownership manifest"):
        bundle_module._load_bundle(root, manifest)


def test_safe_relative_rejects_parent_and_absolute_paths() -> None:
    with pytest.raises(SkillBundleError, match="Unsafe"):
        bundle_module._safe_relative("../secret")
    with pytest.raises(SkillBundleError, match="Unsafe"):
        bundle_module._safe_relative("/absolute")


def test_resource_reader_enforces_file_total_and_count_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = _fixture(tmp_path)
    monkeypatch.setattr(bundle_module, "_MAX_FILE_BYTES", 1)
    with pytest.raises(SkillBundleError, match="file is too large"):
        bundle_module._read_resource_files(root)

    monkeypatch.setattr(bundle_module, "_MAX_FILE_BYTES", 1_000_000)
    monkeypatch.setattr(bundle_module, "_MAX_BUNDLE_BYTES", 1)
    with pytest.raises(SkillBundleError, match="total size"):
        bundle_module._read_resource_files(root)

    monkeypatch.setattr(bundle_module, "_MAX_BUNDLE_BYTES", 5_000_000)
    monkeypatch.setattr(bundle_module, "_MAX_FILES", 1)
    with pytest.raises(SkillBundleError, match="file-count"):
        bundle_module._read_resource_files(root)


def test_resource_reader_accepts_verified_hardlinks(
    tmp_path: Path,
) -> None:
    root, manifest = _fixture(tmp_path)
    os.link(root / "SKILL.md", tmp_path / "cached-skill.md")
    os.link(manifest, tmp_path / "cached-manifest.json")

    loaded = bundle_module._load_bundle(root, manifest)

    assert loaded.version == "1.2.3"


def test_resource_reader_reports_enumeration_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = _fixture(tmp_path)
    original_iterdir = Path.iterdir

    def broken_iterdir(path: Path):
        if path == root:
            raise OSError("blocked")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", broken_iterdir)
    with pytest.raises(SkillBundleError, match="Cannot enumerate"):
        bundle_module._read_resource_files(root)


def test_resource_reader_rejects_a_symlink_when_supported(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    linked = root / "linked.md"
    try:
        linked.symlink_to(root / "SKILL.md")
    except OSError:
        pytest.skip("symlinks are not available")
    with pytest.raises(SkillBundleError, match="cannot be a link"):
        bundle_module._read_resource_files(root)


def test_resource_reader_rejects_a_linked_directory_when_supported(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    linked = root / "linked"
    try:
        linked.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are not available")
    with pytest.raises(SkillBundleError, match="cannot be a link"):
        bundle_module._read_resource_files(root)


def test_resource_reader_handles_non_path_and_non_file_resources() -> None:
    resource = MagicMock()
    bundle_module._reject_unsafe_local_resource(resource)

    child = MagicMock()
    child.name = "special"
    child.is_dir.return_value = False
    child.is_file.return_value = False
    root = MagicMock()
    root.is_dir.return_value = True
    root.iterdir.return_value = [child]
    with pytest.raises(SkillBundleError, match="not a regular file"):
        bundle_module._read_resource_files(root)


def test_resource_reader_reports_stat_and_read_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = _fixture(tmp_path)
    source = root / "SKILL.md"
    original_stat = Path.stat

    def broken_stat(path: Path, *args, **kwargs):
        if path == source:
            raise OSError("blocked")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    monkeypatch.setattr(Path, "is_junction", lambda _path: False)
    monkeypatch.setattr(Path, "stat", broken_stat)
    with pytest.raises(SkillBundleError, match="Cannot inspect"):
        bundle_module._reject_unsafe_local_resource(source)

    monkeypatch.setattr(Path, "stat", original_stat)
    original_read = Path.read_bytes

    def broken_read(path: Path) -> bytes:
        if path == source:
            raise OSError("blocked")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", broken_read)
    with pytest.raises(SkillBundleError, match="Cannot read"):
        bundle_module._read_resource_files(root)


def test_manifest_rejects_invalid_file_entry_and_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest = _fixture(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["files"] = {"SKILL.md": []}
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(SkillBundleError, match="invalid file entry"):
        bundle_module._load_bundle(root, manifest)

    _write_manifest(root, manifest)
    monkeypatch.setattr(bundle_module, "_MAX_FILES", 1)
    with pytest.raises(SkillBundleError, match="file-count"):
        bundle_module._load_bundle(root, manifest)
