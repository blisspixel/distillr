"""Tests for the public library package export surface."""

import distill.library as library


def test_library_public_exports_include_path_and_state_helpers():
    expected_exports = {
        "ARTIFACT_SUFFIXES",
        "LEGACY_ARTIFACT_NAMES",
        "ProvenanceFields",
        "ChannelInfo",
        "ChannelState",
        "Library",
        "TopicWatchEntry",
        "WatchEntry",
        "artifact_path",
        "sanitize_topic",
        "write_markdown_artifact",
    }

    assert expected_exports <= set(library.__all__)
    assert len(library.__all__) == len(set(library.__all__))
    for name in expected_exports:
        assert hasattr(library, name)


def test_library_public_imports_remain_available():
    from distill.library import Library, artifact_path, sanitize_topic

    assert Library is library.Library
    assert artifact_path is library.artifact_path
    assert sanitize_topic is library.sanitize_topic
