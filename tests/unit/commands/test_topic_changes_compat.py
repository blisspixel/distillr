"""Compatibility coverage for the legacy topic-change import path."""

from __future__ import annotations


def test_topic_changes_compat_module_is_canonical_module():
    import distill.cli_support.topic_changes as compat
    import distill.commands._topic_changes as canonical

    assert compat is canonical
    assert compat.topic_change_snapshot is canonical.topic_change_snapshot
