# pyright: strict
"""Measure packaging and fresh-process user experience on a disposable corpus."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
import tomllib
import zipfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TypedDict, cast

import psutil

from benchmarks.corpus_scale.generator import DEFAULT_SEED, generated_corpus

RESULT_SCHEMA_VERSION = "user-experience-result.v1"
DEFAULT_ITERATIONS = 20
DEFAULT_WARMUPS = 1
EXPORT_SCALE = 1_000
OPERATION_NAMES = ("cli_version", "cli_help", "export_bundle", "export_okf")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ISO_TIMESTAMP_RE = re.compile(
    rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_SECRET_NAME_RE = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
_SOURCE_ROOT = Path(__file__).resolve().parents[2]


class CommandSample(TypedDict):
    wall_ns: int
    cpu_ns: int
    peak_rss_bytes: int
    returncode: int
    result_count: int
    result_digest: str


class CommandResult(TypedDict):
    sample: CommandSample
    stdout: bytes
    stderr: bytes


def _nearest_rank(values: Sequence[int], percentile: float) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _summary(samples: Sequence[CommandSample]) -> dict[str, object]:
    wall = [sample["wall_ns"] for sample in samples]
    cpu = [sample["cpu_ns"] for sample in samples]
    peak = [sample["peak_rss_bytes"] for sample in samples]
    result: dict[str, object] = {
        "sample_count": len(samples),
        "min_wall_ns": min(wall),
        "p50_wall_ns": _nearest_rank(wall, 0.50),
        "max_wall_ns": max(wall),
        "p50_cpu_ns": _nearest_rank(cpu, 0.50),
        "max_peak_rss_bytes": max(peak),
    }
    if len(samples) >= 20:
        result["p95_wall_ns"] = _nearest_rank(wall, 0.95)
    return result


def _json_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _project_version(source_root: Path = _SOURCE_ROOT) -> str:
    raw = tomllib.loads((source_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = raw.get("project")
    if not isinstance(project, dict):
        raise ValueError("benchmark pyproject has no project table")
    value = cast("Mapping[str, object]", project).get("version")
    if not isinstance(value, str) or not value:
        raise ValueError("benchmark pyproject has no project version")
    return value


def _installed_version() -> str:
    try:
        return version("distillr")
    except PackageNotFoundError:
        return ""


def source_fingerprint(source_root: Path = _SOURCE_ROOT) -> tuple[str, int]:
    """Fingerprint source that can affect this evidence, normalizing newlines."""

    root = source_root.resolve()
    candidates: set[Path] = set()
    for directory in (root / "distill", root / "benchmarks"):
        if directory.is_dir():
            candidates.update(path for path in directory.rglob("*.py") if path.is_file())
    for name in ("pyproject.toml", "uv.lock"):
        path = root / name
        if path.is_file():
            candidates.add(path)
    if not candidates:
        raise ValueError(f"no benchmark source files found under {root}")
    digest = hashlib.sha256()
    for path in sorted(candidates, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest(), len(candidates)


def _environment() -> dict[str, object]:
    fingerprint, source_files = source_fingerprint()
    project = _project_version()
    installed = _installed_version()
    return {
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "generated_at": datetime.now(UTC).isoformat(),
        "installed_distill_version": installed,
        "installed_distill_version_matches_project": installed == project,
        "operating_system": platform.system(),
        "platform_release": platform.release(),
        "processor": platform.processor(),
        "project_version": project,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "source_file_count": source_files,
        "source_fingerprint_kind": "normalized-source-tree-sha256",
        "source_fingerprint_sha256": fingerprint,
    }


def _artifact(path: Path, expected_suffix: str) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.name.endswith(expected_suffix):
        raise ValueError(f"expected a {expected_suffix} artifact: {path}")
    payload = resolved.read_bytes()
    if not payload:
        raise ValueError(f"artifact is empty: {path}")
    return {
        "filename": resolved.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _sanitized_environment(library_root: Path, scratch_root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if _SECRET_NAME_RE.search(key) is None and not key.startswith("COV_CORE_")
    }
    environment.update(
        {
            "DISTILL_OUTPUT_DIR": str(library_root),
            "DISTILL_COST_MODE": "no-metered",
            "DISTILL_NO_PREFLIGHT": "1",
            "DISTILL_NO_UPDATE_CHECK": "1",
            "NO_COLOR": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "TMPDIR": str(scratch_root),
        }
    )
    if os.name == "nt":
        environment["TEMP"] = str(scratch_root)
        environment["TMP"] = str(scratch_root)
    return environment


def _process_usage(processes: Sequence[psutil.Process]) -> tuple[int, int]:
    cpu_seconds = 0.0
    rss_bytes = 0
    for item in processes:
        try:
            times = item.cpu_times()
            cpu_seconds += float(times.user) + float(times.system)
            rss_bytes += int(item.memory_info().rss)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return int(cpu_seconds * 1_000_000_000), rss_bytes


def measure_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: float,
    result: Callable[[bytes, bytes], tuple[object, int]],
) -> CommandResult:
    """Run one process, recording process-tree CPU, peak RSS, and a stable result."""

    started = time.perf_counter_ns()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdout=stdout_file,
            stderr=stderr_file,
        )
        monitored = psutil.Process(process.pid)
        process_tree = [monitored]
        peak_rss = 0
        cpu_ns = 0
        deadline = time.monotonic() + timeout_seconds
        next_child_refresh = 0.0
        while process.poll() is None:
            now = time.monotonic()
            if now >= next_child_refresh:
                process_tree = [monitored]
                with suppress(psutil.AccessDenied, psutil.NoSuchProcess):
                    process_tree.extend(monitored.children(recursive=True))
                next_child_refresh = now + 0.1
            current_cpu, current_rss = _process_usage(process_tree)
            cpu_ns = max(cpu_ns, current_cpu)
            peak_rss = max(peak_rss, current_rss)
            if now >= deadline:
                process.kill()
                process.wait()
                raise TimeoutError(
                    f"benchmark command timed out after {timeout_seconds:.1f}s: {command[0]}"
                )
            time.sleep(0.01)
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()
    wall_ns = time.perf_counter_ns() - started
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace")[-2_000:]
        raise RuntimeError(f"benchmark command failed ({process.returncode}): {message}")
    value, result_count = result(stdout, stderr)
    sample: CommandSample = {
        "wall_ns": wall_ns,
        "cpu_ns": cpu_ns,
        "peak_rss_bytes": peak_rss,
        "returncode": process.returncode,
        "result_count": result_count,
        "result_digest": _json_digest(value),
    }
    return {"sample": sample, "stdout": stdout, "stderr": stderr}


def _normalized_text_result(root: Path) -> Callable[[bytes, bytes], tuple[object, int]]:
    encoded_root = str(root).encode("utf-8")

    def result(stdout: bytes, stderr: bytes) -> tuple[object, int]:
        normalized = stdout.replace(b"\r\n", b"\n").replace(encoded_root, b"<scratch>")
        normalized_stderr = stderr.replace(b"\r\n", b"\n").replace(encoded_root, b"<scratch>")
        value = {
            "stdout_sha256": hashlib.sha256(normalized).hexdigest(),
            "stderr_sha256": hashlib.sha256(normalized_stderr).hexdigest(),
            "stdout_bytes": len(normalized),
            "stderr_bytes": len(normalized_stderr),
        }
        return value, int(bool(normalized))

    return result


def _normalized_payload(payload: bytes, root: Path) -> bytes:
    normalized = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    normalized = normalized.replace(str(root).encode("utf-8"), b"<scratch>")
    return _ISO_TIMESTAMP_RE.sub(b"<timestamp>", normalized)


def _tree_identity(path: Path, root: Path) -> tuple[object, int]:
    if path.is_file() and path.suffix == ".zip":
        rows: list[tuple[str, int, str]] = []
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                payload = _normalized_payload(archive.read(name), root)
                rows.append((name, len(payload), hashlib.sha256(payload).hexdigest()))
        return rows, len(rows)
    rows = []
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        payload = _normalized_payload(item.read_bytes(), root)
        rows.append(
            (
                item.relative_to(path).as_posix(),
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
        )
    return rows, len(rows)


def _corpus_digest(library_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in library_root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(library_root)
        if ".distill" in relative.parts:
            continue
        relative_bytes = relative.as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _scripts_python(venv: Path) -> tuple[Path, Path]:
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    distill = scripts / ("distill.exe" if os.name == "nt" else "distill")
    return python, distill


def _directory_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _distribution_inventory(
    python: Path, cwd: Path, env: Mapping[str, str]
) -> tuple[list[dict[str, str]], str]:
    script = "\n".join(
        (
            "import importlib.metadata as metadata",
            "import json",
            "rows = [{'name': item.metadata.get('Name') or '', 'version': item.version} for item in metadata.distributions()]",
            "assert all(row['name'] and row['version'] for row in rows)",
            "rows.sort(key=lambda row: (row['name'].casefold(), row['version']))",
            "print(json.dumps(rows, sort_keys=True, separators=(',', ':')))",
        )
    )
    result = subprocess.run(
        [str(python), "-I", "-c", script],
        cwd=cwd,
        env=dict(env),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    raw: object = json.loads(result.stdout)
    if not isinstance(raw, list) or not raw:
        raise ValueError("clean install produced no distribution inventory")
    inventory: list[dict[str, str]] = []
    for value in cast("list[object]", raw):
        if not isinstance(value, dict):
            raise ValueError("clean install distribution inventory is invalid")
        row = cast("dict[object, object]", value)
        name = row.get("name")
        installed_version = row.get("version")
        if not isinstance(name, str) or not name or not isinstance(installed_version, str):
            raise ValueError("clean install distribution inventory is invalid")
        inventory.append({"name": name, "version": installed_version})
    return inventory, _json_digest(inventory)


def _verify_installed_version(
    python: Path, expected: str, cwd: Path, env: Mapping[str, str]
) -> None:
    result = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import importlib.metadata as m; print(m.version('distillr'))",
        ],
        cwd=cwd,
        env=dict(env),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.stdout.strip() != expected:
        raise ValueError("clean install did not produce the checked-out project version")


def _operation(
    name: str,
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    iterations: int,
    warmups: int,
    timeout_seconds: float,
    result_factory: Callable[[], Callable[[bytes, bytes], tuple[object, int]]],
) -> dict[str, object]:
    warmup_samples = [
        measure_command(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            result=result_factory(),
        )["sample"]
        for _ in range(warmups)
    ]
    samples = [
        measure_command(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            result=result_factory(),
        )["sample"]
        for _ in range(iterations)
    ]
    digests = {sample["result_digest"] for sample in [*warmup_samples, *samples]}
    if len(digests) != 1:
        raise ValueError(f"{name} output changed between samples")
    return {
        "name": name,
        "status": "ok",
        "warmup_samples": warmup_samples,
        "first_start_sample": warmup_samples[0] if warmup_samples else None,
        "samples": samples,
        "summary": _summary(samples),
        "network": "fail-closed",
        "result_digests_stable": True,
    }


def run_user_experience(
    wheel: Path,
    sdist: Path,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    warmups: int = DEFAULT_WARMUPS,
    export_scale: int = EXPORT_SCALE,
    uv_executable: Path | None = None,
) -> dict[str, object]:
    """Run the canonical user-experience suite in a disposable workspace."""

    if iterations < 1 or warmups < 0 or export_scale < 1:
        raise ValueError("iterations and export_scale must be positive; warmups cannot be negative")
    project_version = _project_version()
    artifact_rows = {
        "wheel": _artifact(wheel, ".whl"),
        "sdist": _artifact(sdist, ".tar.gz"),
    }
    uv_path = (uv_executable or Path(shutil.which("uv") or "")).resolve()
    if not uv_path.is_file():
        raise ValueError("uv executable was not found")
    source_before, _ = source_fingerprint()

    with tempfile.TemporaryDirectory(prefix="distill-user-experience-") as temporary:
        scratch = Path(temporary).resolve()
        venv = scratch / "clean-install"
        empty_library = scratch / "empty-library"
        empty_library.mkdir()
        install_env = _sanitized_environment(empty_library, scratch)
        create = measure_command(
            [str(uv_path), "venv", "--python", sys.executable, str(venv)],
            cwd=scratch,
            env=install_env,
            timeout_seconds=120,
            result=_normalized_text_result(scratch),
        )
        python, distill = _scripts_python(venv)
        install = measure_command(
            [
                str(uv_path),
                "--no-cache",
                "pip",
                "install",
                "--python",
                str(python),
                "--index-url",
                "https://pypi.org/simple",
                str(wheel.resolve()),
            ],
            cwd=scratch,
            env=install_env,
            timeout_seconds=600,
            result=_normalized_text_result(scratch),
        )
        _verify_installed_version(python, project_version, scratch, install_env)
        installed_distributions, inventory_digest = _distribution_inventory(
            python, scratch, install_env
        )
        install_receipt = {
            "status": "ok",
            "source": "local-wheel",
            "dependency_index": "https://pypi.org/simple",
            "cache_state": "disabled",
            "network": "pypi-dependency-resolution",
            "venv_create": create["sample"],
            "package_install": install["sample"],
            "total_wall_ns": create["sample"]["wall_ns"] + install["sample"]["wall_ns"],
            "installed_environment_bytes": _directory_bytes(venv),
            "installed_distribution_count": len(installed_distributions),
            "installed_distributions": installed_distributions,
            "installed_distribution_inventory_sha256": inventory_digest,
            "installed_version": project_version,
            "installed_version_matches_project": True,
        }

        with generated_corpus(scale=export_scale, seed=DEFAULT_SEED) as corpus:
            command_env = _sanitized_environment(corpus.library_root, scratch)
            corpus_before = _corpus_digest(corpus.library_root)
            output_root = corpus.library_root.parent / "output"
            bundle_path = output_root / f"corpus-{corpus.topic}-bundle.zip"
            okf_path = output_root / f"okf-{corpus.topic}"

            operations = [
                _operation(
                    "cli_version",
                    [str(distill), "--version"],
                    cwd=scratch,
                    env=command_env,
                    iterations=iterations,
                    warmups=warmups,
                    timeout_seconds=30,
                    result_factory=lambda: _normalized_text_result(scratch),
                ),
                _operation(
                    "cli_help",
                    [str(distill), "--help"],
                    cwd=scratch,
                    env=command_env,
                    iterations=iterations,
                    warmups=warmups,
                    timeout_seconds=30,
                    result_factory=lambda: _normalized_text_result(scratch),
                ),
                _operation(
                    "export_bundle",
                    [
                        str(distill),
                        "--quiet",
                        "export",
                        corpus.topic,
                        "--what",
                        "bundle",
                        "--format",
                        "bundle",
                    ],
                    cwd=scratch,
                    env=command_env,
                    iterations=iterations,
                    warmups=warmups,
                    timeout_seconds=180,
                    result_factory=lambda: (
                        lambda _stdout, _stderr: _tree_identity(bundle_path, scratch)
                    ),
                ),
                _operation(
                    "export_okf",
                    [
                        str(distill),
                        "--quiet",
                        "export",
                        corpus.topic,
                        "--what",
                        "bundle",
                        "--format",
                        "okf",
                    ],
                    cwd=scratch,
                    env=command_env,
                    iterations=iterations,
                    warmups=warmups,
                    timeout_seconds=180,
                    result_factory=lambda: (
                        lambda _stdout, _stderr: _tree_identity(okf_path, scratch)
                    ),
                ),
            ]
            corpus_after = _corpus_digest(corpus.library_root)
            if corpus_before != corpus_after:
                raise ValueError("user-experience operations modified the authoritative corpus")
            corpus_receipt = {
                "scale": export_scale,
                "seed": DEFAULT_SEED,
                "topic": corpus.topic,
                "source_counts": corpus.manifest.source_counts,
                "before_digest": corpus_before,
                "after_digest": corpus_after,
                "unchanged": True,
            }

        uninstall = measure_command(
            [str(uv_path), "pip", "uninstall", "--python", str(python), "distillr"],
            cwd=scratch,
            env=install_env,
            timeout_seconds=120,
            result=_normalized_text_result(scratch),
        )
        uninstall_receipt = {
            "status": "ok",
            "sample": uninstall["sample"],
            "dependencies_retained": True,
        }

    source_after, _ = source_fingerprint()
    if source_before != source_after:
        raise ValueError("benchmark source changed during measurement")
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "suite": "user-experience",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": _environment(),
        "artifacts": artifact_rows,
        "execution": {
            "iterations": iterations,
            "warmups": warmups,
            "p95_minimum_samples": 20,
            "process_state": "fresh-child-per-sample",
            "first_start_policy": "first-successful-invocation-before-measured-loop",
            "filesystem_cache_state": "uncontrolled-host-state",
            "timing_policy": "advisory",
            "credentials": "stripped",
            "rss_sample_interval_ms": 10,
            "child_refresh_interval_ms": 100,
        },
        "install": install_receipt,
        "operations": operations,
        "export_corpus": corpus_receipt,
        "uninstall": uninstall_receipt,
        "source_integrity": {
            "before_digest": source_before,
            "after_digest": source_after,
            "unchanged": True,
        },
    }


def result_exit_code(result: Mapping[str, object]) -> int:
    """Return nonzero for correctness or integrity failure, never for timing."""

    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        return 1
    if cast("Mapping[str, object]", result.get("install", {})).get("status") != "ok":
        return 1
    operations_value = result.get("operations")
    if not isinstance(operations_value, list):
        return 1
    operations = cast("list[object]", operations_value)
    if len(operations) != len(OPERATION_NAMES):
        return 1
    if any(
        not isinstance(row, dict) or cast("Mapping[str, object]", row).get("status") != "ok"
        for row in operations
    ):
        return 1
    source = cast("Mapping[str, object]", result.get("source_integrity", {}))
    corpus = cast("Mapping[str, object]", result.get("export_corpus", {}))
    uninstall = cast("Mapping[str, object]", result.get("uninstall", {}))
    return int(
        source.get("unchanged") is not True
        or corpus.get("unchanged") is not True
        or uninstall.get("status") != "ok"
    )


__all__ = [
    "DEFAULT_ITERATIONS",
    "DEFAULT_WARMUPS",
    "EXPORT_SCALE",
    "OPERATION_NAMES",
    "RESULT_SCHEMA_VERSION",
    "measure_command",
    "result_exit_code",
    "run_user_experience",
    "source_fingerprint",
]
