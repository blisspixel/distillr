"""Metadata contracts for quality gates shared by local and CI workflows."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[2]


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
