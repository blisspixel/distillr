"""Release metadata contracts that protect fresh downstream installations."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_editable_lock_version_matches_project_version() -> None:
    """Release bumps must keep the editable root package current in uv.lock."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    editable_roots = [
        package
        for package in lock["package"]
        if package.get("name") == "distillr" and package.get("source") == {"editable": "."}
    ]

    assert len(editable_roots) == 1
    assert editable_roots[0]["version"] == pyproject["project"]["version"]


def test_mcp_runtime_dependency_stays_on_graduated_v2_line() -> None:
    """The graduated SDK line is v2; v3 needs its own compatibility review."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "mcp>=2.2.0,<3" in pyproject["project"]["dependencies"]


def _version_at_least(version: str, floor: tuple[int, ...]) -> bool:
    parts: list[int] = []
    for piece in version.split("."):
        digits = ""
        for character in piece:
            if not character.isdigit():
                break
            digits += character
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) >= floor


def _locked_version(name: str) -> str:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = [package["version"] for package in lock["package"] if package.get("name") == name]
    assert len(versions) == 1
    return versions[0]


def test_entailment_extra_requires_the_reviewed_transformers_floor() -> None:
    """HHEM's reviewed class loads on Transformers 5.17+, which contains the
    custom-generation consent fix and the earlier patched advisories."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extra = pyproject["project"]["optional-dependencies"]["entailment"]

    assert "transformers>=5.17,<6" in extra
    assert "huggingface-hub>=1.31,<3" in extra
    assert _version_at_least(_locked_version("transformers"), (5, 17))


def test_runtime_certifi_floor_is_in_project_metadata_and_the_lock() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "certifi>=2026.10.19" in pyproject["project"]["dependencies"]
    assert _version_at_least(_locked_version("certifi"), (2026, 10, 19))


def test_repaired_pip_stays_in_the_dev_lock_and_out_of_runtime() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "pip>=26.2.2" in pyproject["dependency-groups"]["dev"]
    assert not any(item.startswith("pip") for item in pyproject["project"]["dependencies"])
    assert _version_at_least(_locked_version("pip"), (26, 2, 2))


def test_remaining_audit_floors_are_in_metadata_and_the_lock() -> None:
    """Keep the packages pip-audit still flagged on 2026-10-24 above their fixes."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extra = pyproject["project"]["optional-dependencies"]["entailment"]

    assert "pypdf>=6.21.2" in pyproject["project"]["dependencies"]
    assert "opentelemetry-api>=1.45.1" in pyproject["project"]["dependencies"]
    assert "filelock>=4.2.1,<5" in extra
    assert "setuptools>=84.1.0" in extra
    assert "virtualenv>=21.14.9" in pyproject["dependency-groups"]["dev"]
    assert _version_at_least(_locked_version("pypdf"), (6, 21, 2))
    assert _version_at_least(_locked_version("opentelemetry-api"), (1, 45, 1))
    assert _version_at_least(_locked_version("filelock"), (4, 2, 1))
    assert _version_at_least(_locked_version("setuptools"), (84, 1, 0))
    assert _version_at_least(_locked_version("virtualenv"), (21, 14, 9))


def test_production_code_does_not_call_the_unpatched_transformers_loaders() -> None:
    """CVE-2026-80047 writes custom generation code before consent. The other
    high advisories are save_pretrained traversal and LightGlue initialization."""
    banned = ("load_custom_generate", "save_pretrained", "LightGlue")
    offenders: list[str] = []
    for path in (ROOT / "distill").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in banned:
            if name in text:
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    assert offenders == []
