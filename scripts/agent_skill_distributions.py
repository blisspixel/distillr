"""Generate and verify Distill's cross-client Agent Skill distributions."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import stat
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILL = PurePosixPath("skills/distill-corpus")
CANONICAL_EVALS = PurePosixPath("evals/distill-corpus")
PLUGIN_ROOT = PurePosixPath("plugins/distill-corpus")
BUNDLED_ROOT = PurePosixPath("distill/resources/agent-skills")
BUNDLED_SKILL = BUNDLED_ROOT / "distill-corpus"
BUNDLED_MANIFEST = BUNDLED_ROOT / "distill-corpus.manifest.json"
CODEX_MARKETPLACE = PurePosixPath(".agents/plugins/marketplace.json")
CLAUDE_MARKETPLACE = PurePosixPath(".claude-plugin/marketplace.json")
GEMINI_EXTENSION = PurePosixPath("gemini-extension.json")
DEFAULT_OUTPUT = ROOT / "agent-dist"
MAX_SKILL_FILE_BYTES = 1_000_000
MAX_SKILL_BYTES = 5_000_000
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
BLOCKED_SKILL_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".distill-install.json",
    "credentials",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
}
BLOCKED_SKILL_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}

PLUGIN_DESCRIPTION = (
    "Read, verify, and curate a receipt-backed Distill research corpus, including bounded "
    "active-session worker handoffs."
)


class DistributionError(ValueError):
    """Raised when a source or generated distribution violates its contract."""


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode()


def _project_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    try:
        value = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError, TypeError) as exc:
        raise DistributionError(f"Cannot read project.version from {pyproject}") from exc
    if not isinstance(value, str) or SEMVER.fullmatch(value) is None:
        raise DistributionError("project.version must be strict semantic versioning")
    return value


def _validate_relative_path(path: PurePosixPath) -> None:
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise DistributionError(f"Unsafe distribution path: {path}")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _read_source_payload(
    source: Path,
    path: Path,
    *,
    label: str,
) -> tuple[PurePosixPath, bytes]:
    if _is_link(path) or not path.is_file():
        raise DistributionError(f"{label} must contain regular files only: {path}")
    try:
        before = path.stat()
    except OSError as exc:
        raise DistributionError(f"Cannot inspect {label.lower()} file: {path}") from exc
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise DistributionError(f"{label} must contain one-link regular files only: {path}")
    relative = PurePosixPath(path.relative_to(source).as_posix())
    _validate_relative_path(relative)
    lowered_name = relative.name.lower()
    if (
        lowered_name in BLOCKED_SKILL_NAMES
        or relative.suffix.lower() in BLOCKED_SKILL_SUFFIXES
        or "__pycache__" in relative.parts
    ):
        raise DistributionError(f"Blocked file in {label.lower()}: {relative}")
    try:
        payload = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise DistributionError(f"Cannot read {label.lower()} file: {path}") from exc
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity or len(payload) != before.st_size:
        raise DistributionError(f"{label} file changed while being read: {path}")
    if len(payload) > MAX_SKILL_FILE_BYTES:
        raise DistributionError(
            f"Canonical skill file exceeds {MAX_SKILL_FILE_BYTES} bytes: {relative}"
        )
    return relative, payload


def _skill_files(root: Path) -> dict[PurePosixPath, bytes]:
    source = root.joinpath(*CANONICAL_SKILL.parts)
    if _is_link(source) or not source.is_dir():
        raise DistributionError(f"Canonical skill must be a regular directory: {source}")

    def on_error(exc: OSError) -> None:
        raise DistributionError(f"Cannot enumerate canonical skill: {source}") from exc

    files: dict[PurePosixPath, bytes] = {}
    total_bytes = 0
    for directory, directory_names, file_names in source.walk(
        follow_symlinks=False,
        on_error=on_error,
    ):
        for name in directory_names:
            child = directory / name
            if _is_link(child):
                raise DistributionError(f"Canonical skill cannot contain a link: {child}")
        for name in file_names:
            relative, payload = _read_source_payload(
                source,
                directory / name,
                label="Canonical skill",
            )
            total_bytes += len(payload)
            if total_bytes > MAX_SKILL_BYTES:
                raise DistributionError(
                    f"Canonical skill exceeds the {MAX_SKILL_BYTES}-byte distribution limit"
                )
            files[relative] = payload

    if PurePosixPath("SKILL.md") not in files:
        raise DistributionError("Canonical skill is missing SKILL.md")
    return dict(sorted(files.items(), key=lambda item: item[0].as_posix()))


def _eval_files(root: Path) -> dict[PurePosixPath, bytes]:
    source = root.joinpath(*CANONICAL_EVALS.parts)
    if _is_link(source) or not source.is_dir():
        raise DistributionError(f"Canonical eval suite must be a regular directory: {source}")

    def on_error(exc: OSError) -> None:
        raise DistributionError(f"Cannot enumerate canonical eval suite: {source}") from exc

    files: dict[PurePosixPath, bytes] = {}
    total_bytes = 0
    for directory, directory_names, file_names in source.walk(
        follow_symlinks=False,
        on_error=on_error,
    ):
        for name in directory_names:
            child = directory / name
            if _is_link(child):
                raise DistributionError(f"Canonical eval suite cannot contain a link: {child}")
        for name in file_names:
            relative, payload = _read_source_payload(
                source,
                directory / name,
                label="Canonical eval suite",
            )
            total_bytes += len(payload)
            if total_bytes > MAX_SKILL_BYTES:
                raise DistributionError(
                    f"Canonical eval suite exceeds the {MAX_SKILL_BYTES}-byte distribution limit"
                )
            files[relative] = payload

    if not files or not any(path.name == "case.yaml" for path in files):
        raise DistributionError("Canonical eval suite must contain at least one case.yaml")
    return dict(sorted(files.items(), key=lambda item: item[0].as_posix()))


def _tree_digest(files: Mapping[PurePosixPath, bytes]) -> str:
    digest = hashlib.sha256()
    for relative, payload in sorted(files.items(), key=lambda item: item[0].as_posix()):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _bundle_manifest(version: str, skill_files: Mapping[PurePosixPath, bytes]) -> bytes:
    return _json_bytes(
        {
            "schema_version": "distill-agent-skill-bundle.v1",
            "name": "distill-corpus",
            "version": version,
            "bundle_sha256": _tree_digest(skill_files),
            "files": {
                relative.as_posix(): {
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                for relative, payload in sorted(
                    skill_files.items(), key=lambda item: item[0].as_posix()
                )
            },
        }
    )


def _codex_manifest(version: str) -> dict[str, object]:
    return {
        "name": "distill-corpus",
        "version": version,
        "description": PLUGIN_DESCRIPTION,
        "author": {
            "name": "Nick Seal",
            "url": "https://github.com/blisspixel",
        },
        "homepage": "https://github.com/blisspixel/distillr",
        "repository": "https://github.com/blisspixel/distillr",
        "license": "Apache-2.0",
        "keywords": ["research", "corpus", "verification", "distill"],
        "skills": "./skills/",
        "interface": {
            "displayName": "Distill Corpus",
            "shortDescription": "Research and verify a Distill corpus",
            "longDescription": (
                "Read a Distill corpus from plain files, verify claims against source receipts, "
                "curate it through the CLI, and complete bounded active-session worker tasks."
            ),
            "developerName": "Distillr",
            "category": "Productivity",
            "capabilities": [
                "Corpus research",
                "Receipt verification",
                "Bounded worker handoff",
            ],
            "defaultPrompt": (
                "Use $distill-corpus to inspect my Distill research corpus, verify claims against "
                "receipts, and use only the cost route I authorize."
            ),
        },
    }


def _claude_manifest(version: str) -> dict[str, object]:
    return {
        "name": "distill-corpus",
        "description": PLUGIN_DESCRIPTION,
        "version": version,
        "author": {
            "name": "Nick Seal",
            "url": "https://github.com/blisspixel",
        },
        "homepage": "https://github.com/blisspixel/distillr",
        "repository": "https://github.com/blisspixel/distillr",
        "license": "Apache-2.0",
        "keywords": ["research", "corpus", "verification", "distill"],
    }


def _gemini_manifest(version: str, *, name: str) -> dict[str, object]:
    return {
        "name": name,
        "version": version,
        "description": PLUGIN_DESCRIPTION,
    }


def _codex_marketplace() -> dict[str, object]:
    return {
        "name": "distillr",
        "interface": {"displayName": "Distillr"},
        "plugins": [
            {
                "name": "distill-corpus",
                "source": {
                    "source": "local",
                    "path": "./plugins/distill-corpus",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_USE",
                },
                "category": "Productivity",
            }
        ],
    }


def _claude_marketplace(version: str) -> dict[str, object]:
    return {
        "name": "distillr",
        "owner": {
            "name": "Nick Seal",
            "url": "https://github.com/blisspixel",
        },
        "metadata": {
            "description": "Official Distillr agent plugins",
            "version": version,
        },
        "plugins": [
            {
                "name": "distill-corpus",
                "source": "./plugins/distill-corpus",
                "description": PLUGIN_DESCRIPTION,
                "version": version,
                "author": {
                    "name": "Nick Seal",
                    "url": "https://github.com/blisspixel",
                },
                "homepage": "https://github.com/blisspixel/distillr",
                "repository": "https://github.com/blisspixel/distillr",
                "license": "Apache-2.0",
                "keywords": ["research", "corpus", "verification", "distill"],
                "category": "productivity",
            }
        ],
    }


def _plugin_readme(version: str) -> bytes:
    return f"""# Distill Corpus agent plugin

This is the generated, self-contained distribution of the canonical
`skills/distill-corpus/` Agent Skill for Codex, Claude Code, Grok Build, and
Gemini CLI. Version: `{version}`.

Do not edit this directory by hand. Change the canonical skill or the generator,
then run:

```text
uv run python scripts/agent_skill_distributions.py --write
```

Installing this plugin teaches an already active agent how to work with Distill.
It does not grant credentials, select a billing route, or prove that host usage
is included in a subscription.

The generated `evals/` suite is compatible with Claude Code's native plugin
evaluation runner. It is a model-judged behavioral suite, not a deterministic
keyword score and not evidence that another client's router behaves identically.
""".encode()


def expected_tracked_files(root: Path) -> dict[PurePosixPath, bytes]:
    """Return every generated tracked file and its exact expected bytes."""
    version = _project_version(root)
    skill_files = _skill_files(root)
    eval_files = _eval_files(root)
    license_path = root / "LICENSE"
    if license_path.is_symlink() or not license_path.is_file():
        raise DistributionError(f"License must be a regular file: {license_path}")
    try:
        license_bytes = license_path.read_bytes()
    except OSError as exc:
        raise DistributionError(f"Cannot read {license_path}") from exc

    files: dict[PurePosixPath, bytes] = {
        PLUGIN_ROOT / ".codex-plugin/plugin.json": _json_bytes(_codex_manifest(version)),
        PLUGIN_ROOT / ".claude-plugin/plugin.json": _json_bytes(_claude_manifest(version)),
        PLUGIN_ROOT / "gemini-extension.json": _json_bytes(
            _gemini_manifest(version, name="distill-corpus")
        ),
        PLUGIN_ROOT / "README.md": _plugin_readme(version),
        PLUGIN_ROOT / "LICENSE": license_bytes,
        CODEX_MARKETPLACE: _json_bytes(_codex_marketplace()),
        CLAUDE_MARKETPLACE: _json_bytes(_claude_marketplace(version)),
        GEMINI_EXTENSION: _json_bytes(_gemini_manifest(version, name="distillr")),
    }
    for relative, payload in skill_files.items():
        files[PLUGIN_ROOT / "skills/distill-corpus" / relative] = payload
        files[BUNDLED_SKILL / relative] = payload
    for relative, payload in eval_files.items():
        files[PLUGIN_ROOT / "evals" / relative] = payload
    files[BUNDLED_MANIFEST] = _bundle_manifest(version, skill_files)
    return dict(sorted(files.items(), key=lambda item: item[0].as_posix()))


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            handle.write(payload)
            handle.flush()
            temporary_name = handle.name
        Path(temporary_name).replace(path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def write_tracked(root: Path) -> None:
    """Replace the generated plugin and marketplace files from canonical inputs."""
    expected = expected_tracked_files(root)
    generated_roots = (
        (PLUGIN_ROOT, (root / "plugins").resolve()),
        (BUNDLED_ROOT, (root / "distill" / "resources").resolve()),
    )
    for relative, expected_parent in generated_roots:
        path = root.joinpath(*relative.parts)
        resolved = path.resolve()
        if resolved.parent != expected_parent or resolved.name != relative.name:
            raise DistributionError(f"Refusing to replace unexpected generated path: {resolved}")
        if path.is_symlink():
            raise DistributionError(f"Refusing to replace generated symlink: {path}")
        if path.exists():
            shutil.rmtree(path)

    for relative, payload in expected.items():
        _atomic_write(root.joinpath(*relative.parts), payload)


def _actual_generated_files(root: Path, generated_root: PurePosixPath) -> set[PurePosixPath]:
    generated_path = root.joinpath(*generated_root.parts)
    if not generated_path.exists():
        return set()
    if generated_path.is_symlink() or not generated_path.is_dir():
        return {generated_root}

    files: set[PurePosixPath] = set()
    for directory, directory_names, file_names in generated_path.walk(follow_symlinks=False):
        for name in directory_names:
            path = directory / name
            if path.is_symlink():
                files.add(PurePosixPath(path.relative_to(root).as_posix()))
        for name in file_names:
            path = directory / name
            files.add(PurePosixPath(path.relative_to(root).as_posix()))
    return files


def _actual_plugin_files(root: Path) -> set[PurePosixPath]:
    return _actual_generated_files(root, PLUGIN_ROOT)


def check_tracked(root: Path) -> list[str]:
    """Return stable diagnostics for missing, changed, or unexpected generated files."""
    expected = expected_tracked_files(root)
    errors: list[str] = []
    expected_plugin = {path for path in expected if path.is_relative_to(PLUGIN_ROOT)}
    actual_plugin = _actual_plugin_files(root)
    expected_bundle = {path for path in expected if path.is_relative_to(BUNDLED_ROOT)}
    actual_bundle = _actual_generated_files(root, BUNDLED_ROOT)

    for relative in sorted(actual_plugin - expected_plugin, key=PurePosixPath.as_posix):
        errors.append(f"unexpected generated plugin file: {relative}")
    for relative in sorted(actual_bundle - expected_bundle, key=PurePosixPath.as_posix):
        errors.append(f"unexpected generated bundled file: {relative}")
    for relative, payload in expected.items():
        path = root.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            errors.append(f"missing generated file: {relative}")
            continue
        try:
            actual = path.read_bytes()
        except OSError:
            errors.append(f"unreadable generated file: {relative}")
            continue
        if actual != payload:
            errors.append(f"generated file is stale: {relative}")
    return errors


def _zip_bytes(files: Mapping[PurePosixPath, bytes], root_name: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, payload in sorted(files.items(), key=lambda item: item[0].as_posix()):
            _validate_relative_path(relative)
            archive_path = PurePosixPath(root_name) / relative
            info = zipfile.ZipInfo(archive_path.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0x800
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return stream.getvalue()


def build_archives(root: Path, output: Path) -> list[Path]:
    """Build deterministic skill and universal plugin release archives."""
    errors = check_tracked(root)
    if errors:
        raise DistributionError(
            "Generated distributions are stale; run --write first:\n" + "\n".join(errors)
        )

    version = _project_version(root)
    skill_files = _skill_files(root)
    tracked = expected_tracked_files(root)
    plugin_files = {
        path.relative_to(PLUGIN_ROOT): payload
        for path, payload in tracked.items()
        if path.is_relative_to(PLUGIN_ROOT)
    }
    skill_archive = _zip_bytes(skill_files, "distill-corpus")
    plugin_archive = _zip_bytes(plugin_files, "distill-corpus")
    artifacts = {
        f"distill-corpus-{version}.skill": skill_archive,
        f"distill-corpus-{version}.zip": skill_archive,
        f"distill-corpus-plugin-{version}.zip": plugin_archive,
    }

    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, payload in sorted(artifacts.items()):
        path = output / name
        _atomic_write(path, payload)
        written.append(path)
    checksums = "".join(
        f"{hashlib.sha256(payload).hexdigest()}  {name}\n"
        for name, payload in sorted(artifacts.items())
    ).encode()
    checksum_path = output / f"distill-agent-distributions-{version}.sha256"
    _atomic_write(checksum_path, checksums)
    written.append(checksum_path)
    return written


def _emit(message: str) -> None:
    sys.stdout.write(message + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate tracked distributions")
    mode.add_argument("--check", action="store_true", help="verify tracked distributions")
    mode.add_argument("--build", action="store_true", help="build deterministic release archives")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"archive output directory (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        if args.write:
            write_tracked(ROOT)
            _emit("wrote cross-client Agent Skill distributions")
            return 0
        if args.check:
            errors = check_tracked(ROOT)
            for error in errors:
                _emit(error)
            if errors:
                _emit("run `uv run python scripts/agent_skill_distributions.py --write`")
                return 1
            _emit("cross-client Agent Skill distributions are current")
            return 0

        output = args.output.expanduser().resolve()
        for path in build_archives(ROOT, output):
            _emit(f"wrote {path}")
        return 0
    except DistributionError as exc:
        _emit(f"distribution error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
