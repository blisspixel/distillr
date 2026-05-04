"""Distill CLI — thin wiring module.

This module is the public entry point for the ``distill`` command.
All business logic lives in ``distill._cli_impl``; command groups are
also available as standalone Typer sub-apps in ``distill.commands.*``.

The ``app`` and ``main()`` exported here are the canonical runtime
instances used by ``pyproject.toml [project.scripts]``.

Implementation note: we re-export every public and private name from
``_cli_impl`` so that existing test code that monkeypatches attributes
on ``distill.cli`` (e.g. ``monkeypatch.setattr(cli, "resolve_channel_name", ...)``)
continues to work without changes.  This shim will shrink further once
the test suite patches the canonical module paths directly.
"""

from __future__ import annotations

import distill._bootstrap  # noqa: F401 — UTF-8 stdio side-effect

# Re-export everything from _cli_impl so tests that monkeypatch
# attributes on ``distill.cli`` keep working.
from distill._cli_impl import *  # noqa: F403
from distill._cli_impl import (  # noqa: F401 — private names needed by tests
    _auto_skeptical_mode,
    _dedupe_candidates,
    _dedupe_query_strings,
    _default_report_focus,
    _discover_fetch_videos,
    _discover_generate_queries,
    _discover_rerank,
    _display_ranked_discover,
    _effective_days,
    _expand_learning_queries,
    _expand_paper_queries,
    _filter_recent_candidates,
    _format_metric,
    _generate_and_export_topic_brief,
    _heuristic_learning_queries,
    _llm_expand_learning_queries,
    _llm_expand_paper_queries,
    _looks_like_rumor_query,
    _preflight,
    _preview_learning_selection,
    _process_learning_selection,
    _process_site_seed,
    _process_video,
    _replace_case_insensitive,
    _run_learning_command,
    _run_scope_report,
    _run_topic_workflow,
    _select_learning_videos,
    _show_dashboard,
    _strip_intent_terms,
    _strip_noise_terms,
    _validate_learning_options,
    _window_label,
    app,
    console,
    get_config,
    topic_app,
    topic_watch_app,
    watch_app,
)

__all__ = ["app", "main"]


def main() -> None:
    """Entry point for the ``distill`` CLI command."""
    app()
