# pyright: strict
"""Load and verify the canonical Agent Skill bundled in the Python wheel."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, cast

__all__ = ["SkillBundle", "SkillBundleError", "load_bundled_skill", "tree_digest"]

_SCHEMA = "distill-agent-skill-bundle.v1"
_NAME = "distill-corpus"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_MAX_FILE_BYTES = 1_000_000
_MAX_BUNDLE_BYTES = 5_000_000
_MAX_FILES = 256
_INSTALL_MANIFEST = PurePosixPath(".distill-install.json")


class SkillBundleError(ValueError):
    """The packaged skill is missing, malformed, or fails its integrity manifest."""


@dataclass(frozen=True)
class SkillBundle:
    """Verified immutable inputs for one packaged Agent Skill."""

    name: str
    version: str
    bundle_sha256: str
    files: Mapping[PurePosixPath, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))

    @property
    def total_bytes(self) -> int:
        return sum(len(payload) for payload in self.files.values())

    def file_hashes(self) -> dict[str, str]:
        return {
            relative.as_posix(): hashlib.sha256(payload).hexdigest()
            for relative, payload in sorted(self.files.items(), key=lambda item: item[0].as_posix())
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "bundle_sha256": self.bundle_sha256,
            "files": len(self.files),
            "bytes": self.total_bytes,
        }


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SkillBundleError(f"Unsafe bundled skill path: {value}")
    return path


def tree_digest(files: Mapping[PurePosixPath, bytes]) -> str:
    """Return the stable content digest used by build and runtime manifests."""

    digest = hashlib.sha256()
    for relative, payload in sorted(files.items(), key=lambda item: item[0].as_posix()):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _reject_unsafe_local_resource(path: Traversable) -> None:
    if not isinstance(path, Path):
        return
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise SkillBundleError(f"Bundled skill resource cannot be a link: {path}")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise SkillBundleError(f"Cannot inspect bundled skill resource: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise SkillBundleError(f"Bundled skill resource must be a regular file: {path}")


def _visit_resource_files(
    directory: Traversable,
    prefix: PurePosixPath,
    files: dict[PurePosixPath, bytes],
    total_bytes: list[int],
) -> None:
    try:
        children = sorted(directory.iterdir(), key=lambda child: child.name)
    except OSError as exc:
        raise SkillBundleError(f"Cannot enumerate bundled skill resource: {directory}") from exc
    for child in children:
        relative = prefix / child.name
        _safe_relative(relative.as_posix())
        if child.is_dir():
            if isinstance(child, Path) and (
                child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction())
            ):
                raise SkillBundleError(f"Bundled skill resource cannot be a link: {child}")
            _visit_resource_files(child, relative, files, total_bytes)
            continue
        if not child.is_file():
            raise SkillBundleError(f"Bundled skill resource is not a regular file: {child}")
        _reject_unsafe_local_resource(child)
        try:
            payload = child.read_bytes()
        except OSError as exc:
            raise SkillBundleError(f"Cannot read bundled skill resource: {child}") from exc
        if len(payload) > _MAX_FILE_BYTES:
            raise SkillBundleError(f"Bundled skill file is too large: {relative}")
        total_bytes[0] += len(payload)
        if total_bytes[0] > _MAX_BUNDLE_BYTES:
            raise SkillBundleError("Bundled skill exceeds its total size limit")
        files[relative] = payload
        if len(files) > _MAX_FILES:
            raise SkillBundleError("Bundled skill exceeds its file-count limit")


def _read_resource_files(root: Traversable) -> dict[PurePosixPath, bytes]:
    files: dict[PurePosixPath, bytes] = {}

    if not root.is_dir():
        raise SkillBundleError("Bundled distill-corpus skill directory is missing")
    _visit_resource_files(root, PurePosixPath(), files, [0])
    return files


def _manifest_object(manifest: Traversable) -> dict[str, Any]:
    if not manifest.is_file():
        raise SkillBundleError("Bundled distill-corpus integrity manifest is missing")
    _reject_unsafe_local_resource(manifest)
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillBundleError("Bundled distill-corpus integrity manifest is invalid") from exc
    if not isinstance(value, dict):
        raise SkillBundleError("Bundled distill-corpus integrity manifest must be an object")
    return cast(dict[str, Any], value)


def _manifest_files(value: object) -> dict[PurePosixPath, tuple[int, str]]:
    if not isinstance(value, dict) or not value:
        raise SkillBundleError("Bundled skill manifest files must be a non-empty object")
    result: dict[PurePosixPath, tuple[int, str]] = {}
    for raw_relative, raw_metadata in cast(dict[object, object], value).items():
        if not isinstance(raw_relative, str) or not isinstance(raw_metadata, dict):
            raise SkillBundleError("Bundled skill manifest has an invalid file entry")
        relative = _safe_relative(raw_relative)
        metadata = cast(dict[object, object], raw_metadata)
        size = metadata.get("bytes")
        digest = metadata.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or size > _MAX_FILE_BYTES
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise SkillBundleError(f"Bundled skill manifest metadata is invalid: {relative}")
        result[relative] = (size, digest)
    if len(result) > _MAX_FILES:
        raise SkillBundleError("Bundled skill manifest exceeds its file-count limit")
    return result


def _load_bundle(root: Traversable, manifest: Traversable) -> SkillBundle:
    value = _manifest_object(manifest)
    if value.get("schema_version") != _SCHEMA or value.get("name") != _NAME:
        raise SkillBundleError("Bundled skill manifest identity is invalid")
    version = value.get("version")
    bundle_hash = value.get("bundle_sha256")
    if not isinstance(version, str) or _SEMVER.fullmatch(version) is None:
        raise SkillBundleError("Bundled skill manifest version is invalid")
    if not isinstance(bundle_hash, str) or _SHA256.fullmatch(bundle_hash) is None:
        raise SkillBundleError("Bundled skill manifest digest is invalid")

    expected = _manifest_files(value.get("files"))
    actual = _read_resource_files(root)
    if _INSTALL_MANIFEST in actual:
        raise SkillBundleError("Bundled skill cannot contain its install ownership manifest")
    if set(expected) != set(actual):
        raise SkillBundleError("Bundled skill file inventory does not match its manifest")
    for relative, payload in actual.items():
        size, digest = expected[relative]
        if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
            raise SkillBundleError(f"Bundled skill file fails integrity verification: {relative}")
    if tree_digest(actual) != bundle_hash:
        raise SkillBundleError("Bundled skill tree digest does not match its manifest")
    if PurePosixPath("SKILL.md") not in actual:
        raise SkillBundleError("Bundled skill is missing SKILL.md")
    return SkillBundle(
        name=_NAME,
        version=version,
        bundle_sha256=bundle_hash,
        files=actual,
    )


def load_bundled_skill() -> SkillBundle:
    """Load the generated wheel resource and verify every byte before use."""

    package_root = resources.files("distill")
    resource_root = package_root.joinpath("resources", "agent-skills")
    return _load_bundle(
        resource_root.joinpath(_NAME),
        resource_root.joinpath(f"{_NAME}.manifest.json"),
    )
