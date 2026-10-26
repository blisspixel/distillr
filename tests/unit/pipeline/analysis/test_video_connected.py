"""Connected offline acquisition, analysis, verification and artifact controls.

Media and inference transports are inert fixtures. These checks establish
orchestration and evidence delivery, not ASR accuracy, model comprehension,
real-video coverage, or a qualified whole-route privacy guarantee.
"""

import json
import socket
from types import SimpleNamespace

import pytest

from distill.commands._helpers import process_video
from distill.config import DistillConfig
from distill.ingestors.transcribe import TranscriptionResult
from distill.ingestors.youtube.caption_timing import load_caption_evidence, timing_sidecar_path
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library.paths import extract_frontmatter, find_artifact
from distill.library.state import ChannelState
from distill.llm.router import LLM_Response
from distill.pipeline.costs import CostTracker
from distill.pipeline.summary import RunSummary

_FINDING = "The speaker compares two cohorts using an incidents-to-PR ratio."
_CAVEAT = "The result excludes night shifts and does not establish causation."
_TRANSCRIPT = (
    _FINDING
    + "\n"
    + "The speaker explains the protocol and its assumptions. " * 800
    + "\n"
    + _CAVEAT
)
_EXTRACTION = f"## Source evidence\n{_FINDING}\n\n## Qualification\n{_CAVEAT}\n"
_INSIGHT = f"## Findings\n{_FINDING}\n\n## Limits\n{_CAVEAT}\n"


@pytest.fixture
def connected_video(monkeypatch, tmp_path):
    """Keep real orchestration while denying unmocked transports and processes."""
    events = []
    prompts = []
    controls = {
        "transcript": _TRANSCRIPT,
        "fail_analysis": False,
        "empty_pass": None,
        "empty_text": "",
    }
    config = DistillConfig(
        distill_output_dir=tmp_path / "library",
        distill_verify="strict",
        xai_api_key="",
        openai_api_key="",
        scribe_path="",
    )
    video = VideoInfo(
        video_id="synVideo001",
        title="Synthetic offline content qualification",
        upload_date="20261025",
        duration=600,
        url="https://www.youtube.com/watch?v=synVideo001",
        channel_name="Synthetic fixtures",
        description="Metadata is not sufficient evidence of the source's content.",
    )
    directory = config.video_dir_slug("evidence", video.channel_name, video.title, video.video_id)
    state = ChannelState(tmp_path / "state.json")

    def deny_transport(*args, **kwargs):
        pytest.fail("An unmocked network or child-process transport was attempted")

    monkeypatch.setattr(socket.socket, "connect", deny_transport)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_transport)
    monkeypatch.setattr("subprocess.Popen", deny_transport)
    monkeypatch.setattr("distill.ingestors.youtube.transcripts._RETRY_DELAYS", ())

    def captions_unavailable(url, video_id):
        assert url == video.url
        assert video_id == video.video_id
        events.append("captions_failed")

    def download_fixture(url, video_id, destination):
        assert url == video.url
        assert video_id == video.video_id
        events.append("audio_fixture_acquired")
        assert destination == destination.resolve(strict=True)
        media = destination / "fixture.wav"
        # Inert media transport bytes are not passed to any decoder. The real
        # transcription router still snapshots and confines the input file.
        media.write_bytes(b"synthetic local media transport fixture")
        return media, "Synthetic fixtures", 600.0

    def local_asr_fixture(media_path, **kwargs):
        assert media_path.is_file()
        assert media_path.read_bytes() == b"synthetic local media transport fixture"
        assert kwargs["vocabulary_hint"] == "Synthetic fixtures"
        events.append("local_asr_response")
        return TranscriptionResult(
            text=controls["transcript"],
            provider="faster-whisper",
            model="offline-asr-fixture",
            language="en",
            duration_s=600.0,
        )

    def analysis_response(router, *, prompt, call_type, **kwargs):
        prompts.append((call_type, prompt))
        if controls["fail_analysis"]:
            raise RuntimeError("Synthetic analysis transport failed")
        assert _CAVEAT in prompt
        if call_type == "pass1":
            assert _TRANSCRIPT in prompt
            response_text = _EXTRACTION
        else:
            assert call_type == "pass2"
            assert json.dumps(_EXTRACTION)[1:-1] in prompt
            response_text = _INSIGHT
        if controls["empty_pass"] == call_type:
            response_text = controls["empty_text"]
        return LLM_Response(
            text=response_text,
            input_tokens=10,
            output_tokens=20,
            model="offline-analysis-fixture",
            provider_name="ollama",
            provider_type="local",
        )

    monkeypatch.setattr(
        "distill.ingestors.youtube.transcripts._fetch_caption_bundle", captions_unavailable
    )
    monkeypatch.setattr("distill.ingestors.youtube.transcripts._download_audio", download_fixture)
    monkeypatch.setattr("distill.ingestors.transcribe._transcribe_local", local_asr_fixture)
    monkeypatch.setattr("distill.ingestors.transcribe._transcribe_grok", deny_transport)
    monkeypatch.setattr("distill.ingestors.transcribe._transcribe_openai", deny_transport)
    monkeypatch.setattr("distill.pipeline.analysis.video.llm_call", analysis_response)

    def run():
        tracker = CostTracker()
        summary = RunSummary(command="connected-video-offline")
        completed = process_video(
            "evidence", video.channel_name, video, config, tracker, summary, state=state
        )
        return completed, tracker, summary

    return SimpleNamespace(
        run=run,
        video=video,
        directory=directory,
        state=state,
        controls=controls,
        events=events,
        prompts=prompts,
    )


def test_failed_captions_reach_real_asr_routing_and_both_analysis_passes(connected_video):
    harness = connected_video
    completed, tracker, summary = harness.run()
    assert completed is True
    assert harness.events == ["captions_failed", "audio_fixture_acquired", "local_asr_response"]
    assert [kind for kind, _ in harness.prompts] == ["pass1", "pass2"]
    assert _TRANSCRIPT.index(_CAVEAT) > 30_000
    assert _CAVEAT in harness.prompts[0][1]
    assert _CAVEAT in harness.prompts[1][1]
    transcript = find_artifact(harness.directory, "transcript", extension="txt")
    assert transcript.read_text(encoding="utf-8") == _TRANSCRIPT
    evidence = load_caption_evidence(timing_sidecar_path(transcript))
    assert evidence is not None
    assert evidence.source == "asr"
    assert evidence.timing == "unknown"
    assert evidence.cues == ()
    assert len(tracker.transcriptions) == 1
    assert tracker.transcriptions[0].provider == "faster-whisper"
    assert [entry.call_type for entry in tracker.entries] == ["pass1", "pass2"]
    assert tracker.total_cost == 0
    assert harness.state.is_processed(harness.video.video_id)
    assert summary.results[0].success is True
    assert len(summary.output_files) == 1
    insight = summary.output_files[0]
    assert insight.is_file()
    published = insight.read_text(encoding="utf-8")
    assert _CAVEAT in published
    assert extract_frontmatter(published)["caption_timing"] == "unknown"
    verification = find_artifact(harness.directory, "verify", extension="json")
    assert verification.is_file()
    assert json.loads(verification.read_text(encoding="utf-8"))["source"].startswith(
        "metadata.json +"
    )


def test_analysis_failure_keeps_acquired_transcript_and_restart_reuses_it(connected_video):
    harness = connected_video
    harness.controls["fail_analysis"] = True
    completed, tracker, summary = harness.run()
    assert completed is False
    assert summary.results[0].error == "Synthetic analysis transport failed"
    assert not harness.state.is_processed(harness.video.video_id)
    assert not find_artifact(harness.directory, "insights").exists()
    transcript = find_artifact(harness.directory, "transcript", extension="txt")
    assert transcript.read_text(encoding="utf-8") == _TRANSCRIPT
    assert len(tracker.transcriptions) == 1
    acquisition_events = list(harness.events)
    harness.controls["fail_analysis"] = False
    completed, restarted_tracker, restarted_summary = harness.run()
    assert completed is True
    assert harness.events == acquisition_events
    assert restarted_tracker.transcriptions == []
    assert restarted_summary.output_files[0].is_file()
    assert _CAVEAT in restarted_summary.output_files[0].read_text(encoding="utf-8")


@pytest.mark.parametrize("text", ["", " \n"])
def test_empty_local_asr_cannot_complete_from_metadata(connected_video, text):
    harness = connected_video
    harness.controls["transcript"] = text
    completed, _, summary = harness.run()
    assert completed is False
    assert harness.prompts == []
    assert summary.output_files == []
    assert not harness.state.is_processed(harness.video.video_id)
    assert not find_artifact(harness.directory, "insights").exists()


def test_advertised_transcript_without_file_cannot_complete(connected_video, monkeypatch):
    harness = connected_video

    def lost_output(path, text):
        assert path.suffix == ".txt"
        assert text == _TRANSCRIPT

    monkeypatch.setattr("distill.ingestors.youtube.transcripts.atomic_write_text", lost_output)
    completed, _, summary = harness.run()
    assert completed is False
    assert summary.results[0].error == "Empty transcript"
    assert harness.prompts == []
    assert summary.output_files == []
    assert not harness.state.is_processed(harness.video.video_id)


def test_successful_restart_reuses_acquisition_without_claiming_asr_ran_again(connected_video):
    harness = connected_video
    assert harness.run()[0] is True
    original_events = list(harness.events)
    completed, tracker, summary = harness.run()
    assert completed is True
    assert harness.events == original_events
    assert tracker.transcriptions == []
    assert [entry.call_type for entry in tracker.entries] == ["pass1", "pass2"]
    assert summary.output_files[0].is_file()


@pytest.mark.parametrize("stage", ["pass1", "pass2"])
@pytest.mark.parametrize("empty_text", ["", " \n"])
def test_empty_analysis_pass_cannot_complete_and_retry_reuses_acquisition(
    connected_video, stage, empty_text
):
    harness = connected_video
    harness.controls["empty_pass"] = stage
    harness.controls["empty_text"] = empty_text
    completed, tracker, summary = harness.run()
    assert completed is False
    assert f"{stage}" in summary.results[0].error
    assert "analysis is incomplete" in summary.results[0].error
    assert summary.output_files == []
    assert not harness.state.is_processed(harness.video.video_id)
    assert find_artifact(harness.directory, "transcript", extension="txt").is_file()
    expected_calls = ["pass1"] if stage == "pass1" else ["pass1", "pass2"]
    assert [kind for kind, _ in harness.prompts] == expected_calls
    assert [entry.call_type for entry in tracker.entries] == expected_calls
    assert tracker.total_input_tokens == 10 * len(expected_calls)
    assert tracker.total_output_tokens == 20 * len(expected_calls)
    original_events = list(harness.events)
    harness.controls["empty_pass"] = None
    completed, restarted_tracker, restarted_summary = harness.run()
    assert completed is True
    assert harness.events == original_events
    assert restarted_tracker.transcriptions == []
    assert restarted_summary.output_files[0].is_file()


@pytest.mark.parametrize(
    "output_state", ["missing", "empty", "header_only", "invalid_utf8", "outside"]
)
def test_advertised_insight_must_materialize_before_completion(
    connected_video, monkeypatch, output_state
):
    harness = connected_video
    advertised = (
        harness.directory.parent / "escaped_Insights.md"
        if output_state == "outside"
        else harness.directory / "advertised_Insights.md"
    )

    def broken_publication(*args, **kwargs):
        if output_state == "empty":
            advertised.write_text("", encoding="utf-8")
        elif output_state == "header_only":
            advertised.write_text("---\ntype: insights\n---\n", encoding="utf-8")
        elif output_state == "invalid_utf8":
            advertised.write_bytes(b"\xff\xfe")
        elif output_state == "outside":
            advertised.write_text(
                "## Findings\nA readable body outside the video directory.\n", encoding="utf-8"
            )
        return advertised

    monkeypatch.setattr("distill.commands._helpers.write_markdown_artifact", broken_publication)
    completed, _, summary = harness.run()
    assert completed is False
    assert "Published video insight" in summary.results[0].error
    assert summary.output_files == []
    assert not harness.state.is_processed(harness.video.video_id)
    assert find_artifact(harness.directory, "transcript", extension="txt").is_file()
