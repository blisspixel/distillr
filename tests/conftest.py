"""Shared fixtures for Distill tests."""

import json
from datetime import datetime, timedelta

import pytest
from hypothesis import settings as _hypothesis_settings

from distill.config import DistillConfig

# Hypothesis's default 200ms per-example deadline measures wall clock, which
# under coverage instrumentation on a loaded machine (OneDrive sync, parallel
# live runs) fails *random* property tests that pass in isolation -- three
# full-suite runs on 2026-06-11/12 each dropped a different llm/library
# property test with DeadlineExceeded. These suites test correctness, not
# latency; disable the deadline rather than rerolling.
_hypothesis_settings.register_profile("distill", deadline=None)
_hypothesis_settings.load_profile("distill")


def _recent(days_ago: int = 1) -> str:
    """Return a YYYYMMDD date string for `days_ago` days before today."""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")


@pytest.fixture
def config(tmp_path):
    """Create a DistillConfig pointing at a tmp directory."""
    return DistillConfig(
        xai_api_key="test-xai-key",
        gemini_api_key="test-gemini-key",
        openai_api_key="test-openai-key",
        distill_output_dir=tmp_path / "library",
        distill_default_months=3,
    )


@pytest.fixture
def library_with_channels(config):
    """Create a config with a pre-populated library."""
    from distill.library import Library

    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestChannel", "TestChannel")
    lib.add_channel("ai", "https://www.youtube.com/@AnotherChannel", "AnotherChannel")
    lib.add_channel("security", "https://www.youtube.com/@SecChannel", "SecChannel")
    return config, lib


@pytest.fixture
def populated_channel(config):
    """Create a config with a channel that has videos, transcripts, and insights."""
    from distill.library import Library
    from distill.library.state import ChannelState

    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestChannel", "TestChannel")

    # Create video directories with content
    for i in range(3):
        vid_id = f"vid{i:03d}"
        vid_dir = config.video_dir("ai", "TestChannel", vid_id)
        vid_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "video_id": vid_id,
            "title": f"Test Video {i}",
            "upload_date": _recent(i + 1),
            "duration": 600 + i * 100,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
        }
        (vid_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (vid_dir / "transcript.txt").write_text(f"Transcript for video {i}", encoding="utf-8")
        (vid_dir / "insights.md").write_text(
            f'---\nvideo_title: "Test Video {i}"\n---\n\n## Summary\nInsight {i}',
            encoding="utf-8",
        )

    # Mark videos as processed in state
    state_file = config.channel_dir("ai", "TestChannel") / "state.json"
    state = ChannelState(state_file)
    for i in range(3):
        state.mark_processed(f"vid{i:03d}", f"Test Video {i}", _recent(i + 1))

    # Create channel context and synthesis
    ch_dir = config.channel_dir("ai", "TestChannel")
    (ch_dir / "channel_context.md").write_text("Test channel about AI", encoding="utf-8")
    (ch_dir / "synthesis.md").write_text("# Channel Synthesis\nTest synthesis", encoding="utf-8")

    return config, lib
