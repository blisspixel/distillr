from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _python_version_tuple(value: str) -> tuple[int, int]:
    major, minor = value.split(".", 1)
    return int(major), int(minor)


def test_dockerfile_python_base_matches_project_floor() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requires_python = pyproject["project"]["requires-python"]
    floor_match = re.fullmatch(r">=(\d+\.\d+)", requires_python)
    assert floor_match is not None

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    image_match = re.search(r"^FROM python:(\d+\.\d+)-slim$", dockerfile, flags=re.MULTILINE)
    assert image_match is not None

    assert _python_version_tuple(image_match.group(1)) >= _python_version_tuple(
        floor_match.group(1)
    )


def test_docker_context_excludes_local_runtime_state() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    ignored_paths = {
        line.strip() for line in dockerignore if line.strip() and not line.startswith("#")
    }

    assert ".agent/" in ignored_paths
    assert ".venv/" in ignored_paths
    assert "library/" in ignored_paths
    assert "logs/" in ignored_paths
    assert "output/" in ignored_paths
    assert "tmp/" in ignored_paths
