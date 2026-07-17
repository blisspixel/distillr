"""Tests for managed Agent Skill installation and export."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from distill.agent_skills import lifecycle as lifecycle_module
from distill.agent_skills.bundle import SkillBundle, load_bundled_skill
from distill.agent_skills.lifecycle import (
    CLIENTS,
    SkillInstallError,
    apply_install,
    export_skill,
    inspect_install,
    native_client_guidance,
    remove_install,
    resolve_install_target,
)


@pytest.fixture(scope="module")
def bundle() -> SkillBundle:
    return load_bundled_skill()


def _target(tmp_path: Path) -> Path:
    return tmp_path / ".agents" / "skills" / "distill-corpus"


def _write_unmanaged(bundle: SkillBundle, target: Path) -> None:
    for relative, payload in bundle.files.items():
        path = target.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def test_resolve_install_target_uses_documented_client_locations(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    expected = {
        "portable": (".agents", "skills"),
        "codex": (".agents", "skills"),
        "claude": (".claude", "skills"),
        "gemini": (".gemini", "skills"),
        "grok": (".grok", "skills"),
        "antigravity": (".agents", "skills"),
    }
    for client, parts in expected.items():
        assert resolve_install_target(client, "project", project_root=project) == (
            project.resolve().joinpath(*parts, "distill-corpus")
        )
    assert resolve_install_target("antigravity", "user", home=home) == (
        home.resolve() / ".gemini" / "config" / "skills" / "distill-corpus"
    )
    with pytest.raises(SkillInstallError, match="Unknown client"):
        resolve_install_target("unknown", "project", project_root=project)
    with pytest.raises(SkillInstallError, match="Unknown scope"):
        resolve_install_target("codex", "machine", project_root=project)


def test_install_preview_states_adopt_update_and_idempotence(
    tmp_path: Path,
    bundle: SkillBundle,
) -> None:
    target = _target(tmp_path)
    absent = inspect_install(bundle, target, client="portable", scope="project")
    assert absent.state == "absent"
    assert absent.action == "install"
    assert absent.as_dict()["safe"] is True

    installed = apply_install(bundle, target, client="portable", scope="project")
    assert installed.state == "current"
    assert installed.managed is True
    assert apply_install(bundle, target, client="portable", scope="project") == installed

    unmanaged_target = _target(tmp_path / "unmanaged")
    _write_unmanaged(bundle, unmanaged_target)
    unmanaged = inspect_install(bundle, unmanaged_target, client="portable", scope="project")
    assert unmanaged.state == "current-unmanaged"
    assert unmanaged.action == "adopt"
    assert (
        apply_install(bundle, unmanaged_target, client="portable", scope="project").state
        == "current"
    )

    old_bundle = SkillBundle(
        name=bundle.name,
        version="0.1.0",
        bundle_sha256=bundle.bundle_sha256,
        files=bundle.files,
    )
    update_target = _target(tmp_path / "update")
    apply_install(old_bundle, update_target, client="portable", scope="project")
    update = inspect_install(bundle, update_target, client="portable", scope="project")
    assert update.state == "update-available"
    assert update.installed_version == "0.1.0"
    assert (
        apply_install(bundle, update_target, client="portable", scope="project").state == "current"
    )


def test_install_refuses_unmanaged_modified_or_malformed_destinations(
    tmp_path: Path,
    bundle: SkillBundle,
) -> None:
    unmanaged = _target(tmp_path / "unmanaged")
    unmanaged.mkdir(parents=True)
    (unmanaged / "SKILL.md").write_text("mine", encoding="utf-8")
    status = inspect_install(bundle, unmanaged, client="portable", scope="project")
    assert status.state == "conflict"
    with pytest.raises(SkillInstallError, match="unmanaged"):
        apply_install(bundle, unmanaged, client="portable", scope="project")

    modified = _target(tmp_path / "modified")
    apply_install(bundle, modified, client="portable", scope="project")
    (modified / "SKILL.md").write_text("changed", encoding="utf-8")
    status = inspect_install(bundle, modified, client="portable", scope="project")
    assert status.state == "modified"
    assert status.managed is True
    with pytest.raises(SkillInstallError, match="managed files changed"):
        remove_install(bundle, modified, client="portable", scope="project")

    malformed = _target(tmp_path / "malformed")
    apply_install(bundle, malformed, client="portable", scope="project")
    (malformed / ".distill-install.json").write_text("{", encoding="utf-8")
    status = inspect_install(bundle, malformed, client="portable", scope="project")
    assert status.state == "conflict"
    assert "invalid JSON" in status.detail


def test_install_refuses_files_links_and_hardlinks(tmp_path: Path, bundle: SkillBundle) -> None:
    target_file = _target(tmp_path / "file")
    target_file.parent.mkdir(parents=True)
    target_file.write_text("not a directory", encoding="utf-8")
    assert (
        inspect_install(bundle, target_file, client="portable", scope="project").state == "conflict"
    )

    hardlinked = _target(tmp_path / "hardlink")
    apply_install(bundle, hardlinked, client="portable", scope="project")
    original = hardlinked / "SKILL.md"
    other = hardlinked.parent / "other.md"
    original.unlink()
    source = hardlinked / "references" / "gotchas.md"
    os.link(source, other)
    os.link(source, original)
    status = inspect_install(bundle, hardlinked, client="portable", scope="project")
    assert status.state == "unsafe"
    assert "unsafe file" in status.detail


def test_remove_is_idempotent_and_requires_clean_ownership(
    tmp_path: Path,
    bundle: SkillBundle,
) -> None:
    target = _target(tmp_path)
    apply_install(bundle, target, client="portable", scope="project")
    removed = remove_install(bundle, target, client="portable", scope="project")
    assert removed.state == "absent"
    assert remove_install(bundle, target, client="portable", scope="project") == removed

    unmanaged = _target(tmp_path / "unmanaged")
    _write_unmanaged(bundle, unmanaged)
    with pytest.raises(SkillInstallError, match="Refusing to remove"):
        remove_install(bundle, unmanaged, client="portable", scope="project")


def test_export_is_deterministic_checksummed_and_refuses_unsafe_replacement(
    tmp_path: Path,
    bundle: SkillBundle,
) -> None:
    first = tmp_path / "first.skill"
    second = tmp_path / "second.zip"
    first_result = export_skill(bundle, first)
    export_skill(bundle, second)
    assert first.read_bytes() == second.read_bytes()
    assert first_result["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first.with_name("first.skill.sha256").read_text(encoding="ascii") == (
        f"{first_result['sha256']}  first.skill\n"
    )

    with zipfile.ZipFile(first) as archive:
        assert "distill-corpus/SKILL.md" in archive.namelist()
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())

    with pytest.raises(SkillInstallError, match="already exists"):
        export_skill(bundle, first)
    export_skill(bundle, first, overwrite=True)
    with pytest.raises(SkillInstallError, match="must end"):
        export_skill(bundle, tmp_path / "skill.tar")


def test_native_guidance_is_client_specific_and_does_not_prove_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("distill.agent_skills.lifecycle.shutil.which", lambda name: f"/bin/{name}")
    for client in CLIENTS:
        result = native_client_guidance(client, "project")
        assert result["client"] == client
        if client == "portable":
            assert result["binary"] is None
            assert result["preferred_install"] is None
        else:
            assert result["binary_found"] is True
    assert "marketplace" in str(native_client_guidance("codex", "project")["preferred_install"])
    assert "--scope workspace" in str(
        native_client_guidance("gemini", "project")["preferred_install"]
    )
    assert "#plugins/distill-corpus" in str(
        native_client_guidance("grok", "user")["preferred_install"]
    )
    assert native_client_guidance("antigravity", "user")["binary"] == "agy"
    assert "--scope project" in str(native_client_guidance("claude", "project")["preferred_update"])
    assert "--sparse .claude-plugin plugins/distill-corpus" in str(
        native_client_guidance("claude", "project")["preferred_install"]
    )
    with pytest.raises(SkillInstallError, match="Unknown scope"):
        native_client_guidance("codex", "system")


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ([], "must be an object"),
        ({"schema_version": "wrong"}, "identity"),
        (
            {
                "schema_version": "distill-agent-skill-install.v1",
                "name": "distill-corpus",
                "version": "",
                "bundle_sha256": "0" * 64,
                "files": {"SKILL.md": "0" * 64},
            },
            "version",
        ),
        (
            {
                "schema_version": "distill-agent-skill-install.v1",
                "name": "distill-corpus",
                "version": "1.0.0",
                "bundle_sha256": "bad",
                "files": {"SKILL.md": "0" * 64},
            },
            "digest",
        ),
    ],
)
def test_install_manifest_rejects_invalid_contract(value: object, message: str) -> None:
    with pytest.raises(SkillInstallError, match=message):
        lifecycle_module._parsed_install_manifest(json.dumps(value).encode())


@pytest.mark.parametrize(
    "files",
    [
        {},
        {7: "0" * 64},
        {"../SKILL.md": "0" * 64},
        {"SKILL.md": "bad"},
    ],
)
def test_install_manifest_rejects_invalid_file_inventory(files: object) -> None:
    with pytest.raises(SkillInstallError, match="file"):
        lifecycle_module._parsed_file_hashes(files)


def test_install_detects_destination_race(
    tmp_path: Path,
    bundle: SkillBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    original = lifecycle_module.inspect_install
    calls = 0

    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        status = original(*args, **kwargs)
        return replace(status, fingerprint="changed") if calls == 2 else status

    monkeypatch.setattr(lifecycle_module, "inspect_install", changed)
    with pytest.raises(SkillInstallError, match="changed after"):
        apply_install(bundle, target, client="portable", scope="project")


def test_uninstall_detects_destination_race(
    tmp_path: Path,
    bundle: SkillBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    apply_install(bundle, target, client="portable", scope="project")
    original = lifecycle_module.inspect_install
    calls = 0

    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        status = original(*args, **kwargs)
        return replace(status, fingerprint="changed") if calls == 2 else status

    monkeypatch.setattr(lifecycle_module, "inspect_install", changed)
    with pytest.raises(SkillInstallError, match="changed after"):
        remove_install(bundle, target, client="portable", scope="project")


def test_export_refuses_symlink_and_multiply_linked_paths(
    tmp_path: Path,
    bundle: SkillBundle,
) -> None:
    source = tmp_path / "source.skill"
    source.write_bytes(b"source")
    hardlink = tmp_path / "hardlink.skill"
    os.link(source, hardlink)
    with pytest.raises(SkillInstallError, match="one regular file"):
        export_skill(bundle, hardlink, overwrite=True)

    linked = tmp_path / "linked.skill"
    try:
        linked.symlink_to(source)
    except OSError:
        return
    with pytest.raises(SkillInstallError, match="linked export path"):
        export_skill(bundle, linked, overwrite=True)


def test_native_guidance_reports_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("distill.agent_skills.lifecycle.shutil.which", lambda _name: None)
    result = native_client_guidance("claude", "user")
    assert result["binary_found"] is False
    assert "--scope user" in str(result["preferred_install"])


def test_file_payload_reports_inspection_read_and_change_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("content", encoding="utf-8")
    original_lstat = Path.lstat

    def broken_lstat(path: Path):
        if path == source:
            raise OSError("blocked")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", broken_lstat)
    with pytest.raises(SkillInstallError, match="Cannot inspect"):
        lifecycle_module._file_payload(source)

    monkeypatch.setattr(Path, "lstat", original_lstat)
    original_read = Path.read_bytes

    def broken_read(path: Path) -> bytes:
        if path == source:
            raise OSError("blocked")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", broken_read)
    with pytest.raises(SkillInstallError, match="Cannot read"):
        lifecycle_module._file_payload(source)

    monkeypatch.setattr(Path, "read_bytes", lambda _path: b"short")
    with pytest.raises(SkillInstallError, match="changed while being read"):
        lifecycle_module._file_payload(source)


def test_snapshot_and_manifest_enforce_resource_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "skill"
    target.mkdir()
    (target / "one.md").write_text("one", encoding="utf-8")
    (target / "two.md").write_text("two", encoding="utf-8")

    monkeypatch.setattr(lifecycle_module, "_MAX_TOTAL_BYTES", 1)
    with pytest.raises(SkillInstallError, match="total size"):
        lifecycle_module._installed_snapshot(target)

    monkeypatch.setattr(lifecycle_module, "_MAX_TOTAL_BYTES", 1_000_000)
    monkeypatch.setattr(lifecycle_module, "_MAX_FILES", 1)
    with pytest.raises(SkillInstallError, match="file-count"):
        lifecycle_module._installed_snapshot(target)
    with pytest.raises(SkillInstallError, match="inventory is too large"):
        lifecycle_module._parsed_file_hashes({"one.md": "0" * 64, "two.md": "1" * 64})


def test_inspection_rejects_a_linked_target_when_supported(
    tmp_path: Path,
    bundle: SkillBundle,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    try:
        target.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are not available")
    status = inspect_install(bundle, target, client="portable", scope="project")
    assert status.state == "unsafe"
    assert "path component is a link" in status.detail


def test_replace_target_restores_backup_after_failed_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "new.txt").write_text("new", encoding="utf-8")
    original_replace = Path.replace

    def failed_stage_swap(path: Path, target: Path):
        if path == stage:
            raise OSError("simulated swap failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", failed_stage_swap)
    with pytest.raises(OSError, match="simulated swap failure"):
        lifecycle_module._replace_target(stage, destination)
    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"


def test_install_rechecks_links_cleans_stage_and_verifies_result(
    tmp_path: Path,
    bundle: SkillBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path / "linked")
    unsafe_calls = 0

    def appears_linked(_target: Path) -> Path | None:
        nonlocal unsafe_calls
        unsafe_calls += 1
        return _target.parent if unsafe_calls == 2 else None

    monkeypatch.setattr(lifecycle_module, "_unsafe_component", appears_linked)
    with pytest.raises(SkillInstallError, match="linked path component"):
        apply_install(bundle, target, client="portable", scope="project")

    monkeypatch.undo()
    target = _target(tmp_path / "cleanup")

    def fail_write(_bundle: SkillBundle, _stage: Path) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(lifecycle_module, "_write_staged_skill", fail_write)
    with pytest.raises(SkillInstallError, match="Cannot install"):
        apply_install(bundle, target, client="portable", scope="project")
    assert not list(target.parent.glob(".distill-corpus.stage-*"))

    monkeypatch.undo()
    target = _target(tmp_path / "verify")
    original_inspect = lifecycle_module.inspect_install
    calls = 0

    def failed_verification(*args, **kwargs):
        nonlocal calls
        calls += 1
        status = original_inspect(*args, **kwargs)
        return replace(status, state="modified", detail="simulated") if calls == 3 else status

    monkeypatch.setattr(lifecycle_module, "inspect_install", failed_verification)
    with pytest.raises(SkillInstallError, match="post-write verification"):
        apply_install(bundle, target, client="portable", scope="project")


def test_export_rechecks_parent_and_cleans_failed_atomic_write(
    tmp_path: Path,
    bundle: SkillBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "race.skill"
    unsafe_calls = 0

    def appears_linked(_target: Path) -> Path | None:
        nonlocal unsafe_calls
        unsafe_calls += 1
        return output.parent if unsafe_calls == 2 else None

    monkeypatch.setattr(lifecycle_module, "_unsafe_component", appears_linked)
    with pytest.raises(SkillInstallError, match="linked path component"):
        export_skill(bundle, output)
    assert not output.exists()

    monkeypatch.undo()
    output = tmp_path / "atomic.skill"
    original_replace = Path.replace

    def failed_replace(path: Path, target: Path):
        if target == output:
            raise OSError("simulated replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", failed_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        lifecycle_module._atomic_write_bytes(output, b"payload")
    assert not list(tmp_path.glob(".atomic.skill.*.tmp"))


def test_snapshot_reports_walk_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "skill"
    target.mkdir()

    def broken_walk(path: Path, **kwargs):
        on_error = kwargs["on_error"]
        on_error(OSError(5, "blocked", str(path)))
        yield path, [], []

    monkeypatch.setattr(Path, "walk", broken_walk)
    with pytest.raises(SkillInstallError, match="Cannot enumerate"):
        lifecycle_module._installed_snapshot(target)


@pytest.mark.parametrize(
    ("private_name", "public_call", "message"),
    [
        (
            "_apply_install",
            lambda bundle, target: apply_install(
                bundle, target, client="portable", scope="project"
            ),
            "Cannot install",
        ),
        (
            "_remove_install",
            lambda bundle, target: remove_install(
                bundle, target, client="portable", scope="project"
            ),
            "Cannot remove",
        ),
        (
            "_export_skill",
            lambda bundle, target: export_skill(bundle, target.with_suffix(".skill")),
            "Cannot export",
        ),
    ],
)
def test_public_lifecycle_translates_filesystem_errors(
    tmp_path: Path,
    bundle: SkillBundle,
    monkeypatch: pytest.MonkeyPatch,
    private_name: str,
    public_call,
    message: str,
) -> None:
    def fail(*_args, **_kwargs):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(lifecycle_module, private_name, fail)
    with pytest.raises(SkillInstallError, match=message):
        public_call(bundle, tmp_path / "target")
