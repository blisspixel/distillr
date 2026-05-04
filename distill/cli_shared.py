"""Backward-compatible re-exports. Import from distill.commands._helpers instead."""

# Re-export everything from the new location.  The wildcard import covers
# __all__ members.  We also explicitly import names that the old module
# exposed at module scope (used by tests via monkeypatch) but that are NOT
# in __all__ because they are transitive imports, not helpers themselves.
from distill.commands._helpers import *  # noqa: F403

# Transitive imports that the old cli_shared.py had at module scope.
# Tests monkeypatch these on ``distill.cli_shared``, so they must be
# importable from here.
from distill.commands._helpers import (  # noqa: F401
    ChannelState,
    CostTracker,
    ETATracker,
    RunSummary,
    VideoResult,
    __all__,
    analyze_scan,
    analyze_short,
    analyze_video,
    base_frontmatter,
    find_artifact,
    generate_channel_context,
    get_transcript,
    tags_for,
    write_markdown_artifact,
)
