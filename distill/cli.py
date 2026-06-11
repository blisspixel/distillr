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
    _append_topic_change_history,
    _apply_ranked_channel_cap,
    _auto_skeptical_mode,
    _collect_topic_change_details,
    _content_hash,
    _dedupe_candidates,
    _dedupe_query_strings,
    _default_report_focus,
    _discover_fetch_videos,
    _discover_generate_queries,
    _discover_rerank,
    _display_ranked_discover,
    _duration_str,
    _effective_days,
    _expand_learning_queries,
    _expand_paper_queries,
    _file_link,
    _filter_recent_candidates,
    _format_date,
    _format_metric,
    _generate_and_export_topic_brief,
    _heuristic_learning_queries,
    _llm_expand_learning_queries,
    _llm_expand_paper_queries,
    _load_topic_change_history,
    _looks_like_rumor_query,
    _preflight,
    _preview_learning_selection,
    _process_learning_selection,
    _process_site_seed,
    _process_video,
    _RankedDiscoverItem,
    _read_json_file,
    _render_topic_diff_markdown,
    _render_topic_trends_markdown,
    _replace_case_insensitive,
    _resolve_topic_diff_baseline,
    _run_learning_command,
    _run_scope_report,
    _run_topic_workflow,
    _select_learning_videos,
    _show_dashboard,
    _site_section_change_summary,
    _strip_intent_terms,
    _strip_noise_terms,
    _topic_diff_output_path,
    _topic_trend_direction,
    _topic_trends_output_path,
    _topic_watch_alert_lines,
    _truncate_channel_list,
    _validate_learning_options,
    _watch_alerts_output_path,
    _window_label,
    _write_topic_change_briefing,
    _write_watch_alert_digest,
    app,
    concepts_app,
    console,
    get_config,
    topic_app,
    topic_watch_app,
    watch_app,
)

# Register commands defined in dedicated modules (kept out of the 7k-line
# _logic.py). The import side-effect attaches the command to ``app``.
from distill.commands.audit import register as _register_audit
from distill.commands.claude_md import register as _register_claude_md
from distill.commands.concepts import register as _register_concepts_recovery
from distill.commands.ingest import register as _register_ingest

_register_ingest(app)
_register_concepts_recovery(concepts_app)
_register_claude_md(app)
_register_audit(app)

__all__ = ["app", "main"]


def main() -> None:
    """Entry point for the ``distill`` CLI command.

    Wraps the Typer app so that *expected* provider failures (credits exhausted,
    bad key, rate limit) print a clean one-line message instead of a full
    traceback. Unrecognized errors propagate unchanged.
    """
    from distill.llm.errors import describe_provider_error

    app.pretty_exceptions_enable = False
    try:
        app()
    except Exception as exc:
        message = describe_provider_error(exc)
        if message is None:
            raise
        console.print(f"\n[red]{message}[/red]")
        raise SystemExit(1) from exc
