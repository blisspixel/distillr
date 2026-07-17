# pyright: strict
"""Safe install, inspection, removal, and export for the bundled Agent Skill."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, cast

from distill.agent_skills.bundle import SkillBundle
from distill.library.locking import exclusive_path_lock

__all__ = [
    "CLIENTS",
    "SCOPES",
    "InstallStatus",
    "SkillInstallError",
    "apply_install",
    "export_skill",
    "inspect_install",
    "native_client_guidance",
    "remove_install",
    "resolve_install_target",
]

CLIENTS: tuple[str, ...] = (
    "portable",
    "codex",
    "claude",
    "gemini",
    "grok",
    "antigravity",
)
SCOPES: tuple[str, ...] = ("project", "user")

_INSTALL_SCHEMA = "distill-agent-skill-install.v1"
_INSTALL_MANIFEST = ".distill-install.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_FILES = 256
_MAX_FILE_BYTES = 1_000_000
_MAX_TOTAL_BYTES = 5_100_000
_LOCK_TIMEOUT_SECONDS = 30.0

_CLIENT_PATHS: dict[str, dict[str, tuple[str, ...]]] = {
    "portable": {
        "project": (".agents", "skills"),
        "user": (".agents", "skills"),
    },
    "codex": {
        "project": (".agents", "skills"),
        "user": (".agents", "skills"),
    },
    "claude": {
        "project": (".claude", "skills"),
        "user": (".claude", "skills"),
    },
    "gemini": {
        "project": (".gemini", "skills"),
        "user": (".gemini", "skills"),
    },
    "grok": {
        "project": (".grok", "skills"),
        "user": (".grok", "skills"),
    },
    "antigravity": {
        "project": (".agents", "skills"),
        "user": (".gemini", "config", "skills"),
    },
}


class SkillInstallError(ValueError):
    """A requested skill lifecycle action is unsafe or conflicts with local files."""


@dataclass(frozen=True)
class InstallStatus:
    """Ground-truth state of one direct skill installation target."""

    client: str
    scope: str
    destination: Path
    state: str
    action: str
    managed: bool
    safe: bool
    installed_version: str | None = None
    detail: str = ""
    fingerprint: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "client": self.client,
            "scope": self.scope,
            "destination": str(self.destination),
            "state": self.state,
            "action": self.action,
            "managed": self.managed,
            "safe": self.safe,
            "installed_version": self.installed_version,
            "detail": self.detail,
        }


def _validated_name(value: str, valid: tuple[str, ...], label: str) -> str:
    normalized = value.strip().lower()
    if normalized not in valid:
        raise SkillInstallError(f"Unknown {label} '{value}'. Choose: {', '.join(valid)}")
    return normalized


def resolve_install_target(
    client: str,
    scope: str,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve one documented direct-discovery location without creating it."""

    client = _validated_name(client, CLIENTS, "client")
    scope = _validated_name(scope, SCOPES, "scope")
    if scope == "project":
        base = (project_root or Path.cwd()).expanduser().resolve()
    else:
        base = (home or Path.home()).expanduser().resolve()
    return base.joinpath(*_CLIENT_PATHS[client][scope], "distill-corpus")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _unsafe_component(target: Path) -> Path | None:
    for candidate in (*reversed(target.parents), target):
        if _is_link(candidate):
            return candidate
    return None


def _file_payload(path: Path) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise SkillInstallError(f"Cannot inspect installed skill file: {path}") from exc
    if (
        _is_link(path)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size > _MAX_FILE_BYTES
    ):
        raise SkillInstallError(f"Installed skill contains an unsafe file: {path}")
    try:
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise SkillInstallError(f"Cannot read installed skill file: {path}") from exc
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity or len(payload) != before.st_size:
        raise SkillInstallError(f"Installed skill file changed while being read: {path}")
    return payload


def _raise_walk_error(exc: OSError) -> NoReturn:
    raise SkillInstallError(f"Cannot enumerate installed skill: {exc.filename or exc}") from exc


def _installed_snapshot(target: Path) -> tuple[dict[str, str], bytes | None]:
    hashes: dict[str, str] = {}
    manifest: bytes | None = None
    total_bytes = 0
    for directory, directory_names, file_names in target.walk(
        follow_symlinks=False,
        on_error=_raise_walk_error,
    ):
        for name in directory_names:
            child = directory / name
            if _is_link(child):
                raise SkillInstallError(f"Installed skill contains a linked directory: {child}")
        for name in file_names:
            path = directory / name
            payload = _file_payload(path)
            total_bytes += len(payload)
            if total_bytes > _MAX_TOTAL_BYTES:
                raise SkillInstallError("Installed skill exceeds its total size limit")
            relative = PurePosixPath(path.relative_to(target).as_posix())
            if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                raise SkillInstallError(f"Installed skill has an unsafe path: {relative}")
            if relative.as_posix() == _INSTALL_MANIFEST:
                manifest = payload
            else:
                hashes[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
            if len(hashes) > _MAX_FILES:
                raise SkillInstallError("Installed skill exceeds its file-count limit")
    return hashes, manifest


def _manifest_payload(bundle: SkillBundle) -> bytes:
    value = {
        "schema_version": _INSTALL_SCHEMA,
        "name": bundle.name,
        "version": bundle.version,
        "bundle_sha256": bundle.bundle_sha256,
        "files": bundle.file_hashes(),
    }
    return (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _parsed_file_hashes(raw_files: object) -> dict[str, str]:
    if not isinstance(raw_files, dict) or not raw_files:
        raise SkillInstallError("Managed skill install file inventory is invalid")
    files: dict[str, str] = {}
    for raw_relative, raw_digest in cast(dict[object, object], raw_files).items():
        if not isinstance(raw_relative, str) or not isinstance(raw_digest, str):
            raise SkillInstallError("Managed skill install file entry is invalid")
        relative = PurePosixPath(raw_relative)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or _SHA256.fullmatch(raw_digest) is None
        ):
            raise SkillInstallError("Managed skill install file entry is invalid")
        files[relative.as_posix()] = raw_digest
    if len(files) > _MAX_FILES:
        raise SkillInstallError("Managed skill install file inventory is too large")
    return files


def _parsed_install_manifest(payload: bytes) -> tuple[str, str, dict[str, str]]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SkillInstallError("Managed skill install manifest is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SkillInstallError("Managed skill install manifest must be an object")
    data = cast(dict[str, Any], value)
    if data.get("schema_version") != _INSTALL_SCHEMA or data.get("name") != "distill-corpus":
        raise SkillInstallError("Managed skill install manifest identity is invalid")
    version = data.get("version")
    bundle_hash = data.get("bundle_sha256")
    if not isinstance(version, str) or not version:
        raise SkillInstallError("Managed skill install version is invalid")
    if not isinstance(bundle_hash, str) or _SHA256.fullmatch(bundle_hash) is None:
        raise SkillInstallError("Managed skill install digest is invalid")
    return version, bundle_hash, _parsed_file_hashes(data.get("files"))


def _snapshot_fingerprint(hashes: dict[str, str], manifest: bytes | None) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in sorted(hashes.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    if manifest is not None:
        digest.update(hashlib.sha256(manifest).digest())
    return digest.hexdigest()


def _status(
    *,
    client: str,
    scope: str,
    destination: Path,
    state: str,
    action: str,
    managed: bool,
    safe: bool,
    installed_version: str | None = None,
    detail: str = "",
    fingerprint: str = "",
) -> InstallStatus:
    return InstallStatus(
        client=client,
        scope=scope,
        destination=destination,
        state=state,
        action=action,
        managed=managed,
        safe=safe,
        installed_version=installed_version,
        detail=detail,
        fingerprint=fingerprint,
    )


def inspect_install(
    bundle: SkillBundle,
    destination: Path,
    *,
    client: str,
    scope: str,
) -> InstallStatus:
    """Classify an install using exact inventory and ownership ground truth."""

    unsafe = _unsafe_component(destination)
    if unsafe is not None:
        return _status(
            client=client,
            scope=scope,
            destination=destination,
            state="unsafe",
            action="refuse",
            managed=False,
            safe=False,
            detail=f"path component is a link: {unsafe}",
        )
    if not destination.exists():
        return _status(
            client=client,
            scope=scope,
            destination=destination,
            state="absent",
            action="install",
            managed=False,
            safe=True,
            fingerprint="absent",
        )
    if not destination.is_dir():
        return _status(
            client=client,
            scope=scope,
            destination=destination,
            state="conflict",
            action="refuse",
            managed=False,
            safe=False,
            detail="destination exists and is not a directory",
        )
    try:
        hashes, manifest = _installed_snapshot(destination)
    except SkillInstallError as exc:
        return _status(
            client=client,
            scope=scope,
            destination=destination,
            state="unsafe",
            action="refuse",
            managed=False,
            safe=False,
            detail=str(exc),
        )
    fingerprint = _snapshot_fingerprint(hashes, manifest)
    current_hashes = bundle.file_hashes()
    if manifest is None:
        if hashes == current_hashes:
            return _status(
                client=client,
                scope=scope,
                destination=destination,
                state="current-unmanaged",
                action="adopt",
                managed=False,
                safe=True,
                detail="content is current but has no Distill ownership manifest",
                fingerprint=fingerprint,
            )
        return _status(
            client=client,
            scope=scope,
            destination=destination,
            state="conflict",
            action="refuse",
            managed=False,
            safe=False,
            detail="unmanaged destination differs from the bundled skill",
            fingerprint=fingerprint,
        )
    try:
        version, bundle_hash, recorded_hashes = _parsed_install_manifest(manifest)
    except SkillInstallError as exc:
        return _status(
            client=client,
            scope=scope,
            destination=destination,
            state="conflict",
            action="refuse",
            managed=False,
            safe=False,
            detail=str(exc),
            fingerprint=fingerprint,
        )
    if hashes != recorded_hashes:
        return _status(
            client=client,
            scope=scope,
            destination=destination,
            state="modified",
            action="refuse",
            managed=True,
            safe=False,
            installed_version=version,
            detail="managed files changed or the inventory contains unexpected files",
            fingerprint=fingerprint,
        )
    if (
        version == bundle.version
        and bundle_hash == bundle.bundle_sha256
        and recorded_hashes == current_hashes
    ):
        return _status(
            client=client,
            scope=scope,
            destination=destination,
            state="current",
            action="none",
            managed=True,
            safe=True,
            installed_version=version,
            fingerprint=fingerprint,
        )
    return _status(
        client=client,
        scope=scope,
        destination=destination,
        state="update-available",
        action="update",
        managed=True,
        safe=True,
        installed_version=version,
        detail="managed installation is clean and can be updated safely",
        fingerprint=fingerprint,
    )


def _write_staged_skill(bundle: SkillBundle, stage: Path) -> None:
    for relative, payload in bundle.files.items():
        path = stage.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (stage / _INSTALL_MANIFEST).write_bytes(_manifest_payload(bundle))


def _replace_target(stage: Path, destination: Path) -> None:
    if not destination.exists():
        stage.replace(destination)
        return
    backup = Path(tempfile.mkdtemp(dir=destination.parent, prefix=f".{destination.name}.backup-"))
    backup.rmdir()
    destination.replace(backup)
    try:
        stage.replace(destination)
    except BaseException:
        backup.replace(destination)
        raise
    with contextlib.suppress(OSError):
        shutil.rmtree(backup)


def _apply_install(
    bundle: SkillBundle,
    destination: Path,
    *,
    client: str,
    scope: str,
) -> InstallStatus:
    """Install, adopt, or update one safe direct-discovery target."""

    initial = inspect_install(bundle, destination, client=client, scope=scope)
    if initial.action == "none":
        return initial
    if initial.action not in {"install", "adopt", "update"} or not initial.safe:
        raise SkillInstallError(initial.detail or f"Cannot install over state: {initial.state}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    unsafe = _unsafe_component(destination)
    if unsafe is not None:
        raise SkillInstallError(f"Refusing to install through a linked path component: {unsafe}")
    lock_path = destination.parent / f".{bundle.name}.install.lock"
    with exclusive_path_lock(
        lock_path,
        timeout_seconds=_LOCK_TIMEOUT_SECONDS,
        timeout_message=f"Timed out waiting to install {bundle.name}",
    ):
        current = inspect_install(bundle, destination, client=client, scope=scope)
        if current.state != initial.state or current.fingerprint != initial.fingerprint:
            raise SkillInstallError("Skill destination changed after the install preview")
        stage = Path(tempfile.mkdtemp(dir=destination.parent, prefix=f".{bundle.name}.stage-"))
        try:
            _write_staged_skill(bundle, stage)
            _replace_target(stage, destination)
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)

    installed = inspect_install(bundle, destination, client=client, scope=scope)
    if installed.state != "current":
        raise SkillInstallError(
            f"Installed skill failed post-write verification: {installed.detail}"
        )
    return installed


def apply_install(
    bundle: SkillBundle,
    destination: Path,
    *,
    client: str,
    scope: str,
) -> InstallStatus:
    """Install, adopt, or update one safe direct-discovery target."""

    try:
        return _apply_install(bundle, destination, client=client, scope=scope)
    except SkillInstallError:
        raise
    except (OSError, ValueError) as exc:
        raise SkillInstallError(f"Cannot install {bundle.name} at {destination}: {exc}") from exc


def _remove_install(
    bundle: SkillBundle,
    destination: Path,
    *,
    client: str,
    scope: str,
) -> InstallStatus:
    """Remove only a clean installation whose Distill ownership manifest verifies."""

    initial = inspect_install(bundle, destination, client=client, scope=scope)
    if initial.state == "absent":
        return initial
    if (
        initial.state not in {"current", "update-available"}
        or not initial.managed
        or not initial.safe
    ):
        raise SkillInstallError(
            "Refusing to remove an unmanaged or modified skill installation"
            + (f": {initial.detail}" if initial.detail else "")
        )
    lock_path = destination.parent / f".{bundle.name}.install.lock"
    with exclusive_path_lock(
        lock_path,
        timeout_seconds=_LOCK_TIMEOUT_SECONDS,
        timeout_message=f"Timed out waiting to remove {bundle.name}",
    ):
        current = inspect_install(bundle, destination, client=client, scope=scope)
        if current.state != initial.state or current.fingerprint != initial.fingerprint:
            raise SkillInstallError("Skill destination changed after the uninstall preview")
        shutil.rmtree(destination)
    return inspect_install(bundle, destination, client=client, scope=scope)


def remove_install(
    bundle: SkillBundle,
    destination: Path,
    *,
    client: str,
    scope: str,
) -> InstallStatus:
    """Remove only a clean installation whose ownership manifest verifies."""

    try:
        return _remove_install(bundle, destination, client=client, scope=scope)
    except SkillInstallError:
        raise
    except (OSError, ValueError) as exc:
        raise SkillInstallError(f"Cannot remove {bundle.name} from {destination}: {exc}") from exc


def _zip_bytes(bundle: SkillBundle) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, payload in sorted(bundle.files.items(), key=lambda item: item[0].as_posix()):
            archive_path = PurePosixPath(bundle.name) / relative
            info = zipfile.ZipInfo(archive_path.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0x800
            archive.writestr(
                info,
                payload,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return stream.getvalue()


def _check_export_path(path: Path, *, overwrite: bool) -> None:
    if _is_link(path):
        raise SkillInstallError(f"Refusing to replace a linked export path: {path}")
    if not path.exists():
        return
    try:
        metadata = path.stat()
    except OSError as exc:
        raise SkillInstallError(f"Cannot inspect export path: {path}") from exc
    if not overwrite:
        raise SkillInstallError(f"Export path already exists: {path}")
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SkillInstallError(f"Export path must be one regular file: {path}")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _export_skill(
    bundle: SkillBundle,
    output: Path,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    """Write a deterministic .skill or ZIP archive plus a SHA-256 sidecar."""

    output = output.expanduser().absolute()
    if output.suffix.lower() not in {".skill", ".zip"}:
        raise SkillInstallError("Skill export path must end in .skill or .zip")
    checksum_path = output.with_name(f"{output.name}.sha256")
    unsafe = _unsafe_component(output)
    if unsafe is not None and unsafe != output:
        raise SkillInstallError(f"Refusing to export through a linked path component: {unsafe}")
    output.parent.mkdir(parents=True, exist_ok=True)
    _check_export_path(output, overwrite=overwrite)
    _check_export_path(checksum_path, overwrite=overwrite)
    payload = _zip_bytes(bundle)
    digest = hashlib.sha256(payload).hexdigest()
    checksum = f"{digest}  {output.name}\n".encode("ascii")
    lock_path = output.parent / f".{output.name}.lock"
    with exclusive_path_lock(
        lock_path,
        timeout_seconds=_LOCK_TIMEOUT_SECONDS,
        timeout_message=f"Timed out waiting to export {output.name}",
    ):
        unsafe = _unsafe_component(output)
        if unsafe is not None and unsafe != output:
            raise SkillInstallError(f"Refusing to export through a linked path component: {unsafe}")
        _check_export_path(output, overwrite=overwrite)
        _check_export_path(checksum_path, overwrite=overwrite)
        _atomic_write_bytes(output, payload)
        _atomic_write_bytes(checksum_path, checksum)
    return {
        "path": str(output),
        "checksum_path": str(checksum_path),
        "sha256": digest,
        "bytes": len(payload),
        "version": bundle.version,
    }


def export_skill(
    bundle: SkillBundle,
    output: Path,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    """Write a deterministic skill archive and checksum with safe errors."""

    try:
        return _export_skill(bundle, output, overwrite=overwrite)
    except SkillInstallError:
        raise
    except (OSError, ValueError) as exc:
        raise SkillInstallError(f"Cannot export {bundle.name} to {output}: {exc}") from exc


def native_client_guidance(client: str, scope: str) -> dict[str, object]:
    """Return current native package-manager guidance without invoking a client."""

    client = _validated_name(client, CLIENTS, "client")
    scope = _validated_name(scope, SCOPES, "scope")
    if client == "portable":
        return {
            "client": client,
            "binary": None,
            "binary_found": False,
            "preferred_install": None,
            "preferred_update": None,
            "preferred_uninstall": None,
            "note": (
                "Direct .agents/skills fallback for Codex, Gemini, Antigravity project "
                "workspaces, and other Agent Skills clients."
            ),
        }

    binaries = {
        "codex": "codex",
        "claude": "claude",
        "gemini": "gemini",
        "grok": "grok",
        "antigravity": "agy",
    }
    binary = binaries[client]
    found = shutil.which(binary)
    claude_scope = "project" if scope == "project" else "user"
    gemini_scope = "workspace" if scope == "project" else "user"
    guidance: dict[str, tuple[str | None, str | None, str | None, str]] = {
        "codex": (
            "codex plugin marketplace add blisspixel/distillr --sparse .agents/plugins "
            "--sparse plugins/distill-corpus && codex plugin add distill-corpus@distillr",
            "codex plugin marketplace upgrade distillr",
            "codex plugin remove distill-corpus@distillr",
            "Native plugin install preserves marketplace provenance and versioned caching.",
        ),
        "claude": (
            f"claude plugin marketplace add blisspixel/distillr --scope {claude_scope} "
            "--sparse .claude-plugin plugins/distill-corpus && "
            f"claude plugin install distill-corpus@distillr --scope {claude_scope}",
            f"claude plugin update distill-corpus@distillr --scope {claude_scope}",
            f"claude plugin uninstall distill-corpus@distillr --scope {claude_scope}",
            "Native plugin install provides updates and the bundled behavioral eval suite.",
        ),
        "gemini": (
            "gemini skills install https://github.com/blisspixel/distillr.git "
            f"--path skills/distill-corpus --scope {gemini_scope}",
            None,
            f"gemini skills uninstall distill-corpus --scope {gemini_scope}",
            "Gemini has native skill provenance; reinstall explicitly when updating.",
        ),
        "grok": (
            "grok plugin install blisspixel/distillr#plugins/distill-corpus",
            "grok plugin update distill-corpus",
            "grok plugin uninstall distill-corpus",
            "Grok consumes the self-contained Claude-compatible plugin directly.",
        ),
        "antigravity": (
            None,
            None,
            None,
            "Use the verified direct install target until a stable native package manager exists.",
        ),
    }
    install, update, uninstall, note = guidance[client]
    return {
        "client": client,
        "binary": binary,
        "binary_found": found is not None,
        "binary_path": found,
        "preferred_install": install,
        "preferred_update": update,
        "preferred_uninstall": uninstall,
        "note": note,
    }
