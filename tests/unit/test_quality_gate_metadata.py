"""Metadata contracts for quality gates shared by local and CI workflows."""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[2]
LIVE_NETWORK_MODULES = (
    Path("tests/integration/test_integration.py"),
    Path("tests/unit/ingestors/youtube/test_ytdlp_contract.py"),
)


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    raw = cast(dict[object, object], value)
    return {str(key): item for key, item in raw.items()}


def _sequence(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast(list[object], value)


def _load_yaml(path: Path) -> dict[str, object]:
    parsed: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _mapping(parsed)


def test_full_package_pyright_is_blocking_and_matches_local_hook() -> None:
    """CI and pre-commit must enforce the same full-package type boundary."""
    ci = _load_yaml(ROOT / ".github" / "workflows" / "ci.yml")
    jobs = _mapping(ci["jobs"])
    type_job = _mapping(jobs["types"])
    assert type_job.get("continue-on-error", False) is False
    assert "if" not in type_job
    type_steps = [_mapping(step) for step in _sequence(type_job["steps"])]
    pyright_steps = [
        step
        for step in type_steps
        if str(step.get("run", "")).startswith("uv run --frozen pyright ")
    ]
    full_steps = [
        step
        for step in pyright_steps
        if step.get("run") == "uv run --frozen pyright --warnings distill/"
    ]

    assert pyright_steps == full_steps
    assert len(full_steps) == 1
    full_step = full_steps[0]
    assert full_step.get("continue-on-error", False) is False
    assert "if" not in full_step

    pre_commit = _load_yaml(ROOT / ".pre-commit-config.yaml")
    repositories = [_mapping(repo) for repo in _sequence(pre_commit["repos"])]
    local_repository = next(repo for repo in repositories if repo.get("repo") == "local")
    hooks = [_mapping(hook) for hook in _sequence(local_repository["hooks"])]
    pyright_hooks = [hook for hook in hooks if str(hook.get("id", "")).startswith("pyright")]

    assert len(pyright_hooks) == 1
    pyright_hook = pyright_hooks[0]
    assert pyright_hook["entry"] == "uv run --frozen pyright --warnings distill/"
    assert pyright_hook.get("always_run") is True
    effective_stages = pyright_hook.get("stages", pre_commit.get("default_stages"))
    if effective_stages is not None:
        assert "pre-commit" in {str(stage) for stage in _sequence(effective_stages)}


def test_lockfile_freshness_is_blocking_in_ci_and_local_hook() -> None:
    """Frozen sync must not hide stale project or dependency metadata."""
    ci = _load_yaml(ROOT / ".github" / "workflows" / "ci.yml")
    jobs = _mapping(ci["jobs"])
    lint_job = _mapping(jobs["lint"])
    lint_steps = [_mapping(step) for step in _sequence(lint_job["steps"])]
    lock_steps = [step for step in lint_steps if step.get("run") == "uv lock --check"]

    assert len(lock_steps) == 1
    assert lock_steps[0].get("continue-on-error", False) is False
    assert "if" not in lock_steps[0]

    pre_commit = _load_yaml(ROOT / ".pre-commit-config.yaml")
    repositories = [_mapping(repo) for repo in _sequence(pre_commit["repos"])]
    local_repository = next(repo for repo in repositories if repo.get("repo") == "local")
    hooks = [_mapping(hook) for hook in _sequence(local_repository["hooks"])]
    lock_hooks = [hook for hook in hooks if hook.get("id") == "uv-lock-check"]

    assert len(lock_hooks) == 1
    assert lock_hooks[0]["entry"] == "uv lock --check"
    assert lock_hooks[0].get("pass_filenames") is False
    assert lock_hooks[0].get("always_run") is True


def test_default_test_selection_excludes_only_live_network_tests() -> None:
    """Offline integration stays default while remote-service checks opt in."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_config = pyproject["tool"]["pytest"]["ini_options"]
    marker_names = {marker.partition(":")[0] for marker in pytest_config["markers"]}

    assert "live_network" in marker_names
    assert "integration" not in marker_names

    options = shlex.split(pytest_config["addopts"])
    assert options.count("-m") == 1
    marker_index = options.index("-m")
    assert options[marker_index + 1] == "not live_network"
    assert "--strict-markers" in options

    for relative_path in LIVE_NETWORK_MODULES:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "pytestmark = pytest.mark.live_network" in content

    legacy_marker = "pytest.mark." + "integration"
    stale_markers = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").rglob("*.py")
        if legacy_marker in path.read_text(encoding="utf-8")
    ]
    assert stale_markers == []


def test_llm_package_is_centrally_strict() -> None:
    """Every current and future LLM module must inherit strict type checking."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    strict_paths = pyproject["tool"]["pyright"].get("strict", [])

    assert "distill/llm" in strict_paths
