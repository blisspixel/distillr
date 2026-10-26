"""Local frame evidence and restart contracts with inert decoder boundaries."""

import hashlib
import io
import json
import struct
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from distill.ingestors.youtube import local_frames
from distill.ingestors.youtube.local_frames import capture_local_video_frames
from distill.process_resources import ProcessBudgetExceeded


def _png(width=2, height=2):
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = b"\x00" + b"\x11\x22\x33" * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels * height))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def frame_tools(tmp_path, monkeypatch):
    source = tmp_path / "fixture.mp4"
    source.write_bytes(b"synthetic fixture media; decoder boundary mocked")
    root = tmp_path / "frames"
    tools = {}
    for name in ("ffprobe", "ffmpeg"):
        executable = tmp_path / f"{name}.exe"
        executable.write_bytes(b"inert local executable identity")
        tools[name] = str(executable)
    commands = []
    controls = {"duration": b"125.5\n", "missing": False, "frame_bytes": _png()}

    def run(command, output_root, *, deadline, cancelled, output_limit=16 * 1024):
        assert output_root == root
        assert deadline > 0
        assert command[0] in tools.values()
        assert command[command.index("-protocol_whitelist") + 1] == "file,pipe"
        assert "hls" not in command[command.index("-format_whitelist") + 1]
        commands.append(command)
        if command[0] == tools["ffprobe"]:
            assert output_limit == 16 * 1024
            return controls["duration"]
        assert command[command.index("-threads") + 1] == "1"
        assert command[command.index("-frames:v") + 1] == "1"
        assert output_limit == 4 * 1024 * 1024
        assert command[-2:] == ["image2pipe", "pipe:1"]
        assert "-fs" not in command
        return b"" if controls["missing"] else controls["frame_bytes"]

    monkeypatch.setattr(local_frames, "resolve_executable", tools.get)
    monkeypatch.setattr(local_frames, "_run_media_tool", run)
    return SimpleNamespace(
        source=source, root=root, tools=tools, commands=commands, controls=controls
    )


def test_capture_retains_source_and_actual_png_hashes_with_requested_time_basis(frame_tools):
    harness = frame_tools
    result = capture_local_video_frames(
        harness.source, harness.root, timestamps_ms=(0, 60_000, 120_000)
    )
    assert result.status == "complete"
    assert result.duration_ms == 125_500
    assert result.timestamp_basis == "requested_seek_not_measured_pts"
    assert result.source_sha256 == hashlib.sha256(harness.source.read_bytes()).hexdigest()
    assert (harness.root / result.source_relative_path).read_bytes() == harness.source.read_bytes()
    assert [frame.timestamp_ms for frame in result.frames] == [0, 60_000, 120_000]
    assert all(frame.selection_reason == "requested" for frame in result.frames)
    assert result.blind_intervals_ms == ((0, 60_000), (60_000, 120_000), (120_000, 125_500))
    for frame in result.frames:
        data = (harness.root / frame.relative_path).read_bytes()
        assert data == _png()
        assert frame.sha256 == hashlib.sha256(data).hexdigest()
    # Identical PNG bytes are reused without losing requested-time coverage.
    assert len({frame.relative_path for frame in result.frames}) == 1
    assert len(list(harness.root.glob("frame-*.png"))) == 1
    assert len(harness.commands) == 4
    assert not list(harness.root.glob(".frame-*.png"))


def test_restart_reprobes_timing_and_reuses_verified_frame_bytes(frame_tools):
    harness = frame_tools
    first = capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0, 60_000))
    initial_commands = list(harness.commands)
    second = capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0, 60_000))
    assert second == first
    assert len(harness.commands) == len(initial_commands) + 1
    assert harness.commands[-1][0] == harness.tools["ffprobe"]


def test_changed_recipe_does_not_reuse_other_requested_timestamps(frame_tools):
    harness = frame_tools
    capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    capture_local_video_frames(harness.source, harness.root, timestamps_ms=(60_000,))
    captures = [command for command in harness.commands if command[0] == harness.tools["ffmpeg"]]
    assert [command[command.index("-ss") + 1] for command in captures] == ["0.000", "60.000"]
    assert len(list(harness.root.glob("local-frames-*.json"))) == 2


def test_changed_source_has_a_different_snapshot_and_capture_recipe(frame_tools):
    harness = frame_tools
    first = capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    old = (harness.root / first.source_relative_path).read_bytes()
    harness.source.write_bytes(b"a changed synthetic source")
    second = capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    assert first.source_sha256 != second.source_sha256
    assert (harness.root / first.source_relative_path).read_bytes() == old
    assert len(list(harness.root.glob("local-frames-*.json"))) == 2


def test_changed_tool_identity_prevents_recipe_reuse(frame_tools):
    harness = frame_tools
    capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    Path(harness.tools["ffmpeg"]).write_bytes(b"changed inert executable identity")
    capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    assert sum(command[0] == harness.tools["ffmpeg"] for command in harness.commands) == 2


def test_source_containers_cannot_be_playlists_or_remote_inputs(frame_tools):
    harness = frame_tools
    playlist = harness.source.with_suffix(".m3u8")
    playlist.write_text("https://example.invalid/private-media.mp4", encoding="utf-8")
    with pytest.raises(ValueError, match="supported video file"):
        capture_local_video_frames(playlist, harness.root, timestamps_ms=(0,))
    assert harness.commands == []


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_missing_or_changed_advertised_frame_refuses_restart(frame_tools, kind):
    harness = frame_tools
    first = capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    frame = harness.root / first.frames[0].relative_path
    if kind == "missing":
        frame.unlink()
    else:
        frame.write_bytes(_png(3, 2))
    initial_decodes = sum(command[0] == harness.tools["ffmpeg"] for command in harness.commands)
    with pytest.raises(ValueError, match=r"frame|PNG"):
        capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    assert (
        sum(command[0] == harness.tools["ffmpeg"] for command in harness.commands)
        == initial_decodes
    )


@pytest.mark.parametrize("change", ["duration", "blind", "source", "request", "status"])
def test_malformed_retained_manifest_never_qualifies_restart(frame_tools, change):
    harness = frame_tools
    capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    path = next(harness.root.glob("local-frames-*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if change == "duration":
        payload["duration_ms"] += 1
    elif change == "blind":
        payload["blind_intervals_ms"] = []
    elif change == "source":
        payload["source_sha256"] = "x" * 64
    elif change == "request":
        payload["requested_timestamps_ms"] = [1]
    else:
        payload["status"] = "unknown"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))


@pytest.mark.parametrize(
    "duration", [b"0", b"-1", b"nan", b"inf", b"180.0001", b"unknown", b"1\n2"]
)
def test_unknown_or_out_of_budget_duration_refuses_before_frame_decode(frame_tools, duration):
    harness = frame_tools
    harness.controls["duration"] = duration
    with pytest.raises(ValueError):
        capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    assert len(harness.commands) == 1


@pytest.mark.parametrize(
    "timestamps", [(), (0, 0), (0, 1, 2, 3, 4), (-1,), (180_000,), (False,), (1.5,)]
)
def test_invalid_sample_requests_refuse_before_any_tool(frame_tools, timestamps):
    harness = frame_tools
    with pytest.raises(ValueError):
        capture_local_video_frames(harness.source, harness.root, timestamps_ms=timestamps)
    assert harness.commands == []
    assert not harness.root.exists()


@pytest.mark.parametrize("timeout", [0, 121, False, 1.5])
def test_invalid_whole_tool_deadline_refuses_before_any_tool(frame_tools, timeout):
    harness = frame_tools
    with pytest.raises(ValueError):
        capture_local_video_frames(
            harness.source, harness.root, timestamps_ms=(0,), timeout_seconds=timeout
        )
    assert harness.commands == []


def test_requested_time_outside_actual_duration_refuses(frame_tools):
    harness = frame_tools
    with pytest.raises(ValueError, match="measured source duration"):
        capture_local_video_frames(harness.source, harness.root, timestamps_ms=(150_000,))


def test_oversized_source_refuses_before_tool_execution(frame_tools):
    harness = frame_tools
    with harness.source.open("wb") as stream:
        stream.truncate(local_frames.MAX_SOURCE_BYTES + 1)
    with pytest.raises(ValueError, match="100 MiB"):
        capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    assert harness.commands == []


@pytest.mark.parametrize("kind", ["missing", "bad_png", "oversized", "dimensions"])
def test_invalid_decoder_output_is_an_explicit_capture_failure(frame_tools, kind):
    harness = frame_tools
    if kind == "missing":
        harness.controls["missing"] = True
    elif kind == "bad_png":
        harness.controls["frame_bytes"] = b"not an image"
    elif kind == "oversized":
        harness.controls["frame_bytes"] = b"x" * (4 * 1024 * 1024 + 1)
    else:
        harness.controls["frame_bytes"] = _png(1281, 1)
    with pytest.raises(ValueError, match=r"PNG|dimensions"):
        capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))
    assert not list(harness.root.glob(".frame-*.png"))
    assert not list(harness.root.glob("local-frames-*.json"))


def test_cancelled_capture_keeps_completed_samples_for_restart(frame_tools):
    harness = frame_tools

    def cancellation():
        return sum(command[0] == harness.tools["ffmpeg"] for command in harness.commands) >= 1

    first = capture_local_video_frames(
        harness.source, harness.root, timestamps_ms=(0, 60_000), cancelled=cancellation
    )
    assert first.status == "cancelled"
    assert [frame.timestamp_ms for frame in first.frames] == [0]
    restarted = capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0, 60_000))
    assert restarted.status == "complete"
    assert len(restarted.frames) == 2
    assert sum(command[0] == harness.tools["ffmpeg"] for command in harness.commands) == 2


def test_cancelled_before_probe_retains_source_without_inventing_duration(frame_tools):
    harness = frame_tools
    result = capture_local_video_frames(
        harness.source, harness.root, timestamps_ms=(0,), cancelled=lambda: True
    )
    assert result.status == "cancelled"
    assert result.duration_ms == 0
    assert result.frames == ()
    assert result.blind_intervals_ms == ()
    assert (harness.root / result.source_relative_path).is_file()
    assert harness.commands == []


def test_whole_tool_deadline_is_shared_across_probe_and_frames(frame_tools, monkeypatch):
    harness = frame_tools
    moments = iter([100.0, 131.0])
    monkeypatch.setattr(local_frames, "_monotonic", lambda: next(moments))
    with pytest.raises(ValueError, match="whole-tool deadline"):
        capture_local_video_frames(harness.source, harness.root, timestamps_ms=(0,))


def test_tool_runner_sanitizes_credentials_and_closes_bounded_resources(tmp_path, monkeypatch):
    process = MagicMock()
    process.stdout = io.BytesIO(b"125.5\n")
    process.stderr = io.BytesIO(b"bounded diagnostics")
    process.returncode = 0
    process.poll.return_value = 0
    calls = []
    cleanup = []

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return process

    monkeypatch.setenv("XAI_API_KEY", "synthetic-private-token")
    monkeypatch.setenv("PRIVATE_SECRET", "synthetic-private-data")
    monkeypatch.setenv("FFREPORT", "file=unexpected-private-report.log")
    monkeypatch.setattr(local_frames.subprocess, "Popen", spawn)
    monkeypatch.setattr(local_frames, "assign_windows_memory_job", lambda *args, **kwargs: 42)
    monkeypatch.setattr(local_frames, "close_windows_job", lambda job: cleanup.append(job))
    monkeypatch.setattr(
        local_frames, "terminate_isolated_process_tree", lambda child: cleanup.append(child)
    )
    result = local_frames._run_media_tool(
        ["existing-ffprobe", "safe-input"],
        tmp_path,
        deadline=local_frames.time.monotonic() + 10,
        cancelled=None,
    )
    assert result == b"125.5\n"
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    assert calls[0][1]["stdout"] == subprocess.PIPE
    assert "XAI_API_KEY" not in calls[0][1]["env"]
    assert "PRIVATE_SECRET" not in calls[0][1]["env"]
    assert "FFREPORT" not in calls[0][1]["env"]
    assert cleanup == [process, 42]


def test_tool_runner_terminates_before_persisting_oversized_png_output(tmp_path, monkeypatch):
    from distill.process_resources import BoundedByteHead

    process = MagicMock()
    process.stdout, process.stderr = io.BytesIO(), io.BytesIO()
    process.poll.return_value = None
    cleanup = []
    output = BoundedByteHead(4 * 1024 * 1024)
    output.append(b"x" * (4 * 1024 * 1024 + 1))
    monkeypatch.setattr(local_frames.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        local_frames, "start_bounded_pipe_head_drain", lambda *args, **kwargs: (output, MagicMock())
    )
    monkeypatch.setattr(local_frames, "assign_windows_memory_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(local_frames, "close_windows_job", lambda job: None)
    monkeypatch.setattr(
        local_frames, "terminate_isolated_process_tree", lambda child: cleanup.append(child)
    )
    with pytest.raises(ValueError, match="bounded output limit"):
        local_frames._run_media_tool(
            ["existing-tool"],
            tmp_path,
            deadline=local_frames._monotonic() + 10,
            cancelled=None,
            output_limit=4 * 1024 * 1024,
        )
    assert cleanup == [process]
    assert not list(tmp_path.glob("*.png"))


@pytest.mark.parametrize("failure", ["memory", "time", "cancelled"])
def test_tool_runner_terminates_tree_on_budget_or_cancellation(tmp_path, monkeypatch, failure):
    process = MagicMock()
    process.stdout, process.stderr = io.BytesIO(), io.BytesIO()
    process.poll.return_value = None
    cleanup = []
    monkeypatch.setattr(local_frames.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(local_frames, "assign_windows_memory_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(local_frames, "close_windows_job", lambda job: None)
    monkeypatch.setattr(
        local_frames, "terminate_isolated_process_tree", lambda child: cleanup.append(child)
    )
    if failure == "cancelled":
        checks = iter([False, True])
        with pytest.raises(local_frames._CaptureCancelled):
            local_frames._run_media_tool(
                ["existing-tool"],
                tmp_path,
                deadline=local_frames.time.monotonic() + 10,
                cancelled=lambda: next(checks),
            )
    else:

        def exceed(*args, **kwargs):
            raise ProcessBudgetExceeded(failure, 1, 2)

        monkeypatch.setattr(local_frames, "wait_for_process_budget", exceed)
        if failure == "time":
            moments = iter([0.0, 0.0, 20.0])
            monkeypatch.setattr(local_frames, "_monotonic", lambda: next(moments))
        deadline = 10.0 if failure == "time" else local_frames._monotonic() + 10
        with pytest.raises(ValueError, match=r"memory budget|whole-tool deadline"):
            local_frames._run_media_tool(
                ["existing-tool"], tmp_path, deadline=deadline, cancelled=None
            )
    assert cleanup == [process]
