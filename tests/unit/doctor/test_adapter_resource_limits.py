from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from distill.doctor import adapters


class _FakeProbeProcess:
    pid = 271

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def _install_probe_boundary(monkeypatch, process: _FakeProbeProcess):
    observed: dict[str, object] = {}
    cleanup: list[object] = []

    def popen(argv, **kwargs):
        observed.update(argv=argv, kwargs=kwargs)
        return process

    monkeypatch.setattr(adapters.subprocess, "Popen", popen)
    monkeypatch.setattr(adapters, "package_install_context", lambda: ("/trusted", {"PATH": "safe"}))
    monkeypatch.setattr(adapters, "wait_for_process_budget", lambda *args, **kwargs: 0)
    monkeypatch.setattr(adapters, "assign_windows_memory_job", lambda *args, **kwargs: 41)
    monkeypatch.setattr(adapters, "close_windows_job", cleanup.append)
    monkeypatch.setattr(adapters, "terminate_isolated_process_tree", cleanup.append)
    return observed, cleanup


def test_adapter_command_uses_isolated_bounded_binary_pipes(monkeypatch) -> None:
    process = _FakeProbeProcess(b"codex 0.140.0\n")
    observed, cleanup = _install_probe_boundary(monkeypatch, process)

    result = adapters._run_command(("/trusted/codex", "--version"), 7)

    assert result == (0, "codex 0.140.0\n", "")
    assert observed["argv"] == ["/trusted/codex", "--version"]
    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["cwd"] == "/trusted"
    assert kwargs["env"] == {"PATH": "safe"}
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["shell"] is False
    assert kwargs["start_new_session"] is (os.name != "nt")
    assert cleanup == [process, 41]


@pytest.mark.parametrize(
    ("payload", "expected_code", "expected_stdout", "reason"),
    [
        (b"abcd", 0, "abcd", ""),
        (b"abcde", 125, "abcd", "stdout exceeded 4-byte limit"),
        (b"\xff", 125, "", "stdout is not valid UTF-8"),
    ],
)
def test_adapter_command_output_exact_over_and_invalid_encoding(
    monkeypatch, payload: bytes, expected_code: int, expected_stdout: str, reason: str
) -> None:
    monkeypatch.setattr(adapters, "_ADAPTER_PROBE_OUTPUT_BYTES", 4)
    _install_probe_boundary(monkeypatch, _FakeProbeProcess(payload))

    code, stdout, stderr = adapters._run_command(("/trusted/codex", "--version"), 7)

    assert (code, stdout) == (expected_code, expected_stdout)
    assert reason in stderr


def test_adapter_command_timeout_cleans_isolated_tree(monkeypatch) -> None:
    process = _FakeProbeProcess()
    _, cleanup = _install_probe_boundary(monkeypatch, process)
    monkeypatch.setattr(
        adapters,
        "wait_for_process_budget",
        lambda *args, **kwargs: (_ for _ in ()).throw(adapters.ProcessBudgetExceeded("time", 1, 2)),
    )

    code, _, stderr = adapters._run_command(("/trusted/codex", "--version"), 1)

    assert code == 124
    assert "time budget exceeded" in stderr
    assert cleanup == [process, 41]


def test_version_probe_preserves_first_useful_line_when_output_is_blocked() -> None:
    result = adapters._run_command_probes(
        (adapters.CommandProbe("version", ("codex", "--version")),),
        runner=lambda _command, _timeout: (
            125,
            "codex 0.140.0\n",
            "Distill adapter probe blocked: stdout exceeded 4-byte limit",
        ),
        executable="/trusted/codex",
        timeout_seconds=1,
    )

    assert result.version == "codex 0.140.0"
    assert result.blocked_reasons == ["Distill adapter probe blocked: stdout exceeded 4-byte limit"]


def test_config_read_accepts_exact_byte_limit_and_rejects_one_byte_over(
    monkeypatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    content = b'[auth]\nsession = "present"\n'
    config_path.write_bytes(content)
    monkeypatch.setattr(adapters, "_ADAPTER_CONFIG_BYTES", len(content))

    assert "auth.session" in adapters._config_marker_keys(config_path, tmp_path)

    monkeypatch.setattr(adapters, "_ADAPTER_CONFIG_BYTES", len(content) - 1)
    with pytest.raises(adapters._StructuredInputBlocked, match="byte limit"):
        adapters._config_marker_keys(config_path, tmp_path)


def test_config_scan_blocks_symlink_and_invalid_utf8(tmp_path: Path) -> None:
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    outside.write_text('[auth]\nsession = "present"\n', encoding="utf-8")
    linked = config_dir / "config.toml"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    probe = adapters.ConfigProbe("~/.codex/config.toml", (".codex", "config.toml"), ())

    result = adapters._scan_config_probes((probe,), tmp_path)

    assert result.files_found == ["~/.codex/config.toml"]
    assert any("confined regular file" in reason for reason in result.blocked_reasons)

    linked.unlink()
    linked.write_bytes(b"\xff")
    result = adapters._scan_config_probes((probe,), tmp_path)
    assert any("valid UTF-8" in reason for reason in result.blocked_reasons)


def test_structured_marker_walk_blocks_depth_and_node_expansion(monkeypatch) -> None:
    nested: object = "oauth"
    for index in range(5):
        nested = {f"level{index}": nested}
    monkeypatch.setattr(adapters, "_ADAPTER_CONFIG_MAX_DEPTH", 3)

    with pytest.raises(adapters._StructuredInputBlocked, match="depth limit"):
        adapters._flatten_config_keys(nested)

    monkeypatch.setattr(adapters, "_ADAPTER_CONFIG_MAX_DEPTH", 64)
    monkeypatch.setattr(adapters, "_ADAPTER_CONFIG_MAX_NODES", 2)
    with pytest.raises(adapters._StructuredInputBlocked, match="node limit"):
        adapters._flatten_config_keys({"a": 1, "b": 2})


def test_auth_json_input_has_exact_byte_limit_and_actionable_block(monkeypatch) -> None:
    text = json.dumps({"session": "oauth"}, separators=(",", ":"))
    monkeypatch.setattr(adapters, "_ADAPTER_AUTH_JSON_BYTES", len(text.encode("utf-8")))
    assert "session" in adapters._json_marker_keys(text)

    monkeypatch.setattr(adapters, "_ADAPTER_AUTH_JSON_BYTES", len(text.encode("utf-8")) - 1)
    with pytest.raises(adapters._StructuredInputBlocked, match="byte limit"):
        adapters._json_marker_keys(text)


def test_auth_probe_converts_deep_tree_block_to_fixed_reason(monkeypatch) -> None:
    nested: object = "oauth"
    for index in range(5):
        nested = {f"level{index}": nested}
    output = json.dumps(nested)
    monkeypatch.setattr(adapters, "_ADAPTER_CONFIG_MAX_DEPTH", 3)
    probe = adapters.AuthCommandProbe("auth", ("tool", "auth"), (), ("oauth",))

    result = adapters._run_auth_command_probes(
        (probe,),
        runner=lambda _command, _timeout: (0, output, ""),
        executable="/trusted/tool",
        timeout_seconds=1,
    )

    assert result.blocked_reasons == ["auth output blocked: structured input depth limit exceeded"]
