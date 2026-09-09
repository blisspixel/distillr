"""Build the standalone editorial skill and optional client plugin wrappers.

Run from the repository root with python -m scripts.editorial_skill_distributions.
The build uses repository helpers; installed artifacts have no Python dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from scripts import agent_skill_distributions as shared

ROOT = Path(__file__).resolve().parents[1]
NAME = "perspective-editorial"
SKILL = PurePosixPath("skills") / NAME
EVALS = PurePosixPath("evals") / NAME
PLUGIN = PurePosixPath("plugins") / NAME
DESCRIPTION = (
    "Research, plan, write, and review evidence-backed blogs in a private person or company "
    "perspective using available host tools. Distillr and Retonr are optional."
)


def _version(skill: dict[PurePosixPath, bytes]) -> str:
    metadata = shared._agent_skill_frontmatter(skill[PurePosixPath("SKILL.md")]).get("metadata")
    version = metadata.get("version") if isinstance(metadata, dict) else None
    if not isinstance(version, str) or shared.SEMVER.fullmatch(version) is None:
        raise shared.DistributionError(
            "Editorial skill metadata.version must be semantic versioning"
        )
    return version


def _readme(version: str, *, portable: bool = False) -> bytes:
    package = (
        "Agent Plugins 1.0.0 package" if portable else "Claude and Codex compatibility package"
    )
    return f"""# Perspective Editorial

A standalone editorial skill for a private person or company perspective.
Version {version}. This is the {package}. Distillr is not required.

Use the host's existing research, writing, file, and Word export tools. The skill
guides reading, ideas, angle selection, outlining, drafting, a whole-article
rewrite, evidence and prose review, revisions, and Markdown or DOCX delivery.
Capability limits remain visible. A skill cannot itself enforce a dollar cap.
External paid calls require an authorized budget-enforcing adapter.

Copy assets/perspective.example.toml from inside the skill to a private workspace
and edit it for the writer or company. Keep real perspectives, examples, API keys,
receipts, and articles outside this package. Cloud hosts follow their own data
and sharing rules. The example does not enable paid calls.

For GitHub Copilot, copy skills/perspective-editorial into .github/skills/ in a
chosen project or ~/.copilot/skills/ for personal use. For Claude Code, copy it
into .claude/skills/ or ~/.claude/skills/. Claude Cowork uses account skills or
plugins, not the local Claude Code personal skill directory.

For Copilot Cowork's plugin upload or Agents Toolkit import, choose the separate
Claude-compatible archive if using the strict portable archive. A root
plugin.json is not the same layout as .claude-plugin/plugin.json. Use the host's
installation controls and review its permissions. Installation is optional.

Start with: Use perspective-editorial and my private perspective to research this
week's AI news, choose a useful angle, draft, rewrite and critique it, then provide
Markdown and Word. External paid calls are disabled.

Read SKILL.md and its conditional references for the exact procedure. Optional
Distillr and Retonr adapters are documented there. This package activates no MCP
servers, hooks, model downloads, credentials, or scheduled tasks.

This directory is generated from the canonical skill. In the source repository,
edit skills/perspective-editorial and run:

    uv run python -m scripts.editorial_skill_distributions --write

Installation guidance and dated interoperability research:
https://github.com/blisspixel/distillr/blob/main/docs/portable-editorial-skill.md
""".encode()


def expected_files(root: Path) -> dict[PurePosixPath, bytes]:
    """Read only the canonical skill, eval suite, and repository license."""
    skill = shared._skill_files(root, source_path=SKILL)
    version = _version(skill)
    manifest: dict[str, object] = {
        "name": NAME,
        "version": version,
        "description": DESCRIPTION,
        "author": {"name": "Nick Seal"},
        "license": "Apache-2.0",
        "repository": "https://github.com/blisspixel/distillr",
    }
    codex = {
        **manifest,
        "skills": "./skills/",
        "interface": {
            "displayName": "Perspective Editorial",
            "shortDescription": "Research and refine blogs in a person or company voice",
            "longDescription": DESCRIPTION,
            "developerName": "Nick Seal",
            "category": "Productivity",
            "capabilities": ["Research", "Editorial writing", "Perspective review"],
            "defaultPrompt": (
                "Use $perspective-editorial with my private perspective to research, plan, "
                "draft, rewrite, and review an article, then deliver Markdown and DOCX."
            ),
        },
    }
    _, license_bytes = shared._read_source_payload(root, root / "LICENSE", label="License")
    files = {
        PLUGIN / "plugin.json": shared._json_bytes(
            {"$schema": shared.AGENT_PLUGINS_SCHEMA, **manifest}
        ),
        PLUGIN / ".claude-plugin/plugin.json": shared._json_bytes(manifest),
        PLUGIN / ".codex-plugin/plugin.json": shared._json_bytes(codex),
        PLUGIN / "README.md": _readme(version),
        PLUGIN / "LICENSE": license_bytes.rstrip(b"\n") + b"\n",
    }
    files.update({PLUGIN / "skills" / NAME / path: body for path, body in skill.items()})
    files.update(
        {
            PLUGIN / "evals" / path: body
            for path, body in shared._eval_files(root, source_path=EVALS).items()
        }
    )
    return dict(sorted(files.items()))


def _generated_files(root: Path) -> set[PurePosixPath]:
    """Refuse linked generated paths before reading or replacing any content."""
    parent = root / "plugins"
    target = root.joinpath(*PLUGIN.parts)
    if shared._is_link(parent) or shared._is_link(target):
        raise shared.DistributionError("Generated editorial plugin cannot be linked")
    if target.resolve().parent != root.resolve() / "plugins":
        raise shared.DistributionError("Generated editorial plugin escaped its repository")
    if not target.exists():
        return set()
    if not target.is_dir():
        raise shared.DistributionError("Generated editorial plugin must be a directory")
    found: set[PurePosixPath] = set()
    for directory, folders, files in target.walk(follow_symlinks=False):
        for name in folders + files:
            if shared._is_link(directory / name):
                raise shared.DistributionError("Generated editorial plugin cannot contain links")
        for name in files:
            path = directory / name
            if not path.is_file() or path.stat().st_nlink != 1:
                raise shared.DistributionError("Generated editorial files must be one-link files")
            found.add(PurePosixPath(path.relative_to(root).as_posix()))
    return found


def write_tracked(root: Path) -> None:
    """Update this generated plugin without changing any marketplace or runtime bundle."""
    expected = expected_files(root)
    actual = _generated_files(root)
    for relative in sorted(actual - expected.keys()):
        root.joinpath(*relative.parts).unlink()
    for relative, body in expected.items():
        shared._atomic_write(root.joinpath(*relative.parts), body)


def check_tracked(root: Path) -> list[str]:
    expected = expected_files(root)
    actual = _generated_files(root)
    errors = [f"unexpected generated file: {path}" for path in sorted(actual - expected.keys())]
    for relative, body in expected.items():
        if relative not in actual:
            errors.append(f"missing generated file: {relative}")
        elif root.joinpath(*relative.parts).read_bytes() != body:
            errors.append(f"stale generated file: {relative}")
    return errors


def build_archives(root: Path, output: Path) -> list[Path]:
    """Create deterministic standalone, portable, and native compatibility ZIPs."""
    errors = check_tracked(root)
    if errors:
        raise shared.DistributionError("Run --write before building: " + "; ".join(errors))
    skill = shared._skill_files(root, source_path=SKILL)
    version = _version(skill)
    plugin = {path.relative_to(PLUGIN): body for path, body in expected_files(root).items()}
    portable = {
        path: body
        for path, body in plugin.items()
        if path.parts[0] == "skills" or path.as_posix() in {"plugin.json", "LICENSE"}
    }
    portable[PurePosixPath("README.md")] = _readme(version, portable=True)
    standalone = shared._zip_bytes(skill, NAME)
    # Native uploaders expect .claude-plugin/plugin.json at the ZIP root.
    artifacts = {
        f"{NAME}-{version}.skill": standalone,
        f"{NAME}-{version}.zip": standalone,
        f"{NAME}-agent-plugin-{version}.zip": shared._zip_bytes(portable, ""),
        f"{NAME}-plugin-{version}.zip": shared._zip_bytes(plugin, ""),
    }
    checksums = "".join(
        f"{hashlib.sha256(body).hexdigest()}  {name}\n" for name, body in sorted(artifacts.items())
    )
    artifacts[f"{NAME}-{version}.sha256"] = checksums.encode()
    written = []
    for name, body in sorted(artifacts.items()):
        path = output / name
        shared._atomic_write(path, body)
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "agent-dist")
    args = parser.parse_args()
    try:
        if args.write:
            write_tracked(ROOT)
            shared._emit("Wrote standalone editorial plugin")
        elif args.check:
            errors = check_tracked(ROOT)
            shared._emit(json.dumps({"current": not errors, "errors": errors}))
            return int(bool(errors))
        else:
            for path in build_archives(ROOT, args.output.expanduser().resolve()):
                shared._emit(str(path))
    except (shared.DistributionError, OSError) as exc:
        shared._emit(f"Editorial distribution error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
