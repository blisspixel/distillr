# pyright: strict
from __future__ import annotations

import json
from pathlib import Path

from distill.config import DistillConfig
from distill.library.paths import artifact_path
from distill.pipeline.report.materials import (
    channels_for_scope,
    gather_tagged_materials,
    load_syntheses,
    load_tagged_insights,
    read_video_metadata_title_and_id,
)


def test_read_video_metadata_title_and_id_missing_file(tmp_path: Path):
    meta_file = tmp_path / "missing.json"
    title, source_id = read_video_metadata_title_and_id(meta_file, fallback="fallback_id")
    assert title == "fallback_id"
    assert source_id == "fallback_id"


def test_read_video_metadata_title_and_id_corrupt_file(tmp_path: Path):
    meta_file = tmp_path / "corrupt.json"
    meta_file.write_text("{not valid json", encoding="utf-8")
    title, source_id = read_video_metadata_title_and_id(meta_file, fallback="fallback_id")
    assert title == "fallback_id"
    assert source_id == "fallback_id"


def test_read_video_metadata_title_and_id_non_dict(tmp_path: Path):
    meta_file = tmp_path / "list.json"
    meta_file.write_text("[1, 2, 3]", encoding="utf-8")
    title, source_id = read_video_metadata_title_and_id(meta_file, fallback="fallback_id")
    assert title == "fallback_id"
    assert source_id == "fallback_id"


def test_read_video_metadata_title_and_id_valid(tmp_path: Path):
    meta_file = tmp_path / "valid.json"
    meta_file.write_text(
        json.dumps({"title": "Video Title", "video_id": "vid123"}),
        encoding="utf-8",
    )
    title, source_id = read_video_metadata_title_and_id(meta_file, fallback="fallback_id")
    assert title == "Video Title"
    assert source_id == "vid123"


def test_read_video_metadata_title_and_id_empty_fields(tmp_path: Path):
    meta_file = tmp_path / "empty.json"
    meta_file.write_text(
        json.dumps({"title": "", "video_id": None}),
        encoding="utf-8",
    )
    title, source_id = read_video_metadata_title_and_id(meta_file, fallback="fallback_id")
    assert title == "fallback_id"
    assert source_id == "fallback_id"


def test_channels_for_scope_channel_scope(tmp_path: Path):
    config = DistillConfig(distill_output_dir=tmp_path)
    channels = channels_for_scope("topic1", config, scope="channel", channel_name="channelA")
    assert channels == [("topic1", "channelA")]


def test_channels_for_scope_topic_scope(tmp_path: Path):
    config = DistillConfig(distill_output_dir=tmp_path)
    # When channels dir does not exist
    assert channels_for_scope("topic1", config, scope="topic", channel_name=None) == []

    # When channels dir exists
    ch_dir = config.topic_dir("topic1") / "channels" / "channelB"
    ch_dir.mkdir(parents=True, exist_ok=True)
    channels = channels_for_scope("topic1", config, scope="topic", channel_name=None)
    assert channels == [("topic1", "channelB")]


def test_channels_for_scope_all_scope(tmp_path: Path):
    config = DistillConfig(distill_output_dir=tmp_path)
    # When topics dir exists with multiple channels
    ch_dir1 = config.topic_dir("topic1") / "channels" / "channelA"
    ch_dir1.mkdir(parents=True, exist_ok=True)
    ch_dir2 = config.topic_dir("topic2") / "channels" / "channelB"
    ch_dir2.mkdir(parents=True, exist_ok=True)

    channels = channels_for_scope("topic1", config, scope="all", channel_name=None)
    assert ("topic1", "channelA") in channels
    assert ("topic2", "channelB") in channels


def test_load_syntheses_empty(tmp_path: Path):
    config = DistillConfig(distill_output_dir=tmp_path)
    res = load_syntheses("topic1", config, scope="channel", channel_name="channelA")
    assert res == ""


def test_load_syntheses_with_channel_and_topic(tmp_path: Path):
    config = DistillConfig(distill_output_dir=tmp_path)
    ch_dir = config.channel_dir("topic1", "channelA")
    ch_dir.mkdir(parents=True, exist_ok=True)
    ch_synth = artifact_path(ch_dir, "synthesis", identity="topic1_channelA")
    ch_synth.write_text("Channel Synth Content", encoding="utf-8")

    topic_dir = config.topic_dir("topic1")
    topic_dir.mkdir(parents=True, exist_ok=True)
    tp_synth = artifact_path(topic_dir, "topic_synthesis", identity="topic1")
    tp_synth.write_text("Topic Synth Content", encoding="utf-8")

    res = load_syntheses("topic1", config, scope="channel", channel_name="channelA")
    assert "Channel Synth Content" in res
    assert "Topic Synth Content" in res


def test_load_tagged_insights_matches_and_truncates(tmp_path: Path):
    config = DistillConfig(distill_output_dir=tmp_path)
    vdir = config.videos_dir("topic1", "channelA") / "vid1"
    vdir.mkdir(parents=True, exist_ok=True)
    ins_file = artifact_path(vdir, "insights", identity="vid1")
    ins_file.write_text("Insights discussing Microsoft Azure and OpenAI.", encoding="utf-8")
    (vdir / "metadata.json").write_text(
        json.dumps({"title": "Vid 1 Title", "video_id": "vid1"}), encoding="utf-8"
    )

    # Matching keywords
    res = load_tagged_insights(
        "topic1",
        config,
        scope="channel",
        channel_name="channelA",
        keywords=["Microsoft", "OpenAI"],
        max_chars=1000,
    )
    assert "Vid 1 Title" in res
    assert "Microsoft Azure" in res

    # Non-matching keywords
    res_none = load_tagged_insights(
        "topic1",
        config,
        scope="channel",
        channel_name="channelA",
        keywords=["NonExistent"],
        max_chars=1000,
    )
    assert res_none == ""

    # max_chars truncation limit reached
    res_trunc = load_tagged_insights(
        "topic1",
        config,
        scope="channel",
        channel_name="channelA",
        keywords=["Microsoft"],
        max_chars=5,
    )
    assert res_trunc == ""


def test_gather_tagged_materials(tmp_path: Path):
    config = DistillConfig(distill_output_dir=tmp_path)
    vdir = config.videos_dir("topic1", "channelA") / "vid1"
    vdir.mkdir(parents=True, exist_ok=True)
    ins_file = artifact_path(vdir, "insights", identity="vid1")
    ins_file.write_text("Enterprise production deploy ROI and Google cloud.", encoding="utf-8")
    (vdir / "metadata.json").write_text(
        json.dumps({"title": "Enterprise Vid", "video_id": "vid1"}), encoding="utf-8"
    )

    ch_dir = config.channel_dir("topic1", "channelA")
    ch_dir.mkdir(parents=True, exist_ok=True)
    ch_synth = artifact_path(ch_dir, "synthesis", identity="topic1_channelA")
    ch_synth.write_text("Channel Synth Content", encoding="utf-8")

    tagged = gather_tagged_materials("topic1", config, scope="channel", channel_name="channelA")
    assert "vendor_battleground" in tagged
    assert "enterprise_reality" in tagged
    assert "creator_consensus" in tagged
    assert "creator_accuracy" in tagged


def test_load_tagged_insights_edge_cases(tmp_path: Path):
    config = DistillConfig(distill_output_dir=tmp_path)
    # 1. videos_dir does not exist
    res1 = load_tagged_insights(
        "topic1", config, scope="channel", channel_name="no_videos", keywords=["test"]
    )
    assert res1 == ""

    # 2. non-directory file inside videos_dir and missing insights_file
    vroot = config.videos_dir("topic1", "channelA")
    vroot.mkdir(parents=True, exist_ok=True)
    (vroot / "stray_file.txt").write_text("not a dir", encoding="utf-8")
    empty_vid_dir = vroot / "empty_vid"
    empty_vid_dir.mkdir(parents=True, exist_ok=True)

    res2 = load_tagged_insights(
        "topic1", config, scope="channel", channel_name="channelA", keywords=["test"]
    )
    assert res2 == ""


def test_channels_for_scope_all_edge_cases(tmp_path: Path):
    empty_dir = tmp_path / "empty_lib"
    empty_dir.mkdir(parents=True, exist_ok=True)
    config = DistillConfig(distill_output_dir=empty_dir)
    # topics_root does not exist
    assert channels_for_scope("topic1", config, scope="all", channel_name=None) == []

    # topics_root has a file (not dir), and a topic dir without channels dir
    topics_root = config.topics_dir()
    topics_root.mkdir(parents=True, exist_ok=True)
    (topics_root / "stray_file.txt").write_text("not a topic", encoding="utf-8")
    (topics_root / "empty_topic").mkdir(parents=True, exist_ok=True)

    assert channels_for_scope("topic1", config, scope="all", channel_name=None) == []
