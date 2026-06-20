"""CLI business logic - shared command functions and helpers.

This module holds legacy shared implementation for CLI commands. It was
moved from ``distill/_cli_impl.py`` during the 0.7 CLI decomposition.
Individual ``commands/*.py`` modules import the functions they need from
here and register them on their Typer sub-apps.

The ``app`` Typer instance defined here is the canonical top-level app used at
runtime.
"""

import os as os  # compatibility export for distill._cli_impl
import sys

import typer

import distill.pipeline.discovery as _discover_support
from distill._app import app
from distill._version import get_version as _get_version
from distill.banner import show_banner
from distill.cli_shared import (
    console,
)
from distill.cli_shared import (
    resolve_video_channel_name as _shared_resolve_video_channel_name,
)
from distill.commands import _discover_flow as _discover_flow_support
from distill.commands import _learning as _learning_support
from distill.commands import _topic_changes as _topic_changes_support
from distill.commands._helpers import (
    _apply_cost_mode_override,
    _apply_output_mode,
    _apply_verify_override,  # noqa: F401 - compatibility export for distill._cli_impl
    _complete_topic_watch_names,  # noqa: F401 - compatibility export for distill._cli_impl
    _complete_topics,  # noqa: F401 - compatibility export for distill._cli_impl
    _complete_watched_channels,  # noqa: F401 - compatibility export for distill._cli_impl
    _invoke_command,  # noqa: F401 - compatibility export for distill._cli_impl
    _persist_lens,  # noqa: F401 - compatibility export for distill._cli_impl
    _preflight,  # noqa: F401 - compatibility export for distill._cli_impl
    _resolve_intent,  # noqa: F401 - compatibility export for distill._cli_impl
    _truncate_channel_list,  # noqa: F401 - compatibility export for distill._cli_impl
    get_config,
)
from distill.commands._helpers import (
    process_video as _process_video,  # noqa: F401 - compatibility export for distill._cli_impl
)
from distill.commands._helpers import (
    run_scope_report as _run_scope_report,  # noqa: F401 - compatibility export for distill._cli_impl
)

# Doctor check/probe helpers live in distill.doctor.checks; the two used by the
# doctor command (still in this module) are re-imported so it finds them in this
# namespace. init + the MCP doctor tool import from distill.doctor.checks directly.
from distill.ingestors.youtube.discovery import resolve_channel_name
from distill.library import Library  # noqa: F401 - compatibility export for distill.commands.audit

_replace_case_insensitive = _learning_support._replace_case_insensitive
_strip_intent_terms = _learning_support._strip_intent_terms
_strip_noise_terms = _learning_support._strip_noise_terms
_auto_skeptical_mode = _learning_support._auto_skeptical_mode
_effective_days = _learning_support._effective_days
_window_label = _learning_support._window_label
_default_report_focus = _learning_support._default_report_focus
_filter_recent_candidates = _learning_support._filter_recent_candidates
_dedupe_candidates = _learning_support._dedupe_candidates
_format_metric = _learning_support._format_metric
_apply_ranked_channel_cap = _learning_support._apply_ranked_channel_cap
_apply_source_rigor = _learning_support._apply_source_rigor
_dedupe_query_strings = _learning_support._dedupe_query_strings
_heuristic_learning_queries = _learning_support._heuristic_learning_queries
_llm_expand_learning_queries = _learning_support._llm_expand_learning_queries
_llm_expand_paper_queries = _learning_support._llm_expand_paper_queries
_expand_learning_queries = _learning_support._expand_learning_queries
_expand_paper_queries = _learning_support._expand_paper_queries
_select_learning_videos = _learning_support._select_learning_videos
_preview_learning_selection = _learning_support._preview_learning_selection
_run_learning_command = _learning_support._run_learning_command
_process_learning_selection = _learning_support._process_learning_selection
_generate_and_export_topic_brief = _learning_support._generate_and_export_topic_brief
_display_ranked_papers = _learning_support._display_ranked_papers
_display_ranked_videos = _learning_support._display_ranked_videos

_RankedDiscoverItem = _discover_support.RankedDiscoverItem
_discover_generate_queries = _discover_flow_support._discover_generate_queries
_discover_fetch_videos = _discover_flow_support._discover_fetch_videos
_discover_rerank = _discover_flow_support._discover_rerank
_display_ranked_discover = _discover_flow_support._display_ranked_discover
_is_fresh_topic = _discover_flow_support._is_fresh_topic
_sizing_option_line = _discover_flow_support._sizing_option_line
_discover_sizing_flow = _discover_flow_support._discover_sizing_flow
_confirm_discover_ingest = _discover_flow_support._confirm_discover_ingest
_discover_ingest_papers = _discover_flow_support._discover_ingest_papers
_discover_ingest_videos = _discover_flow_support._discover_ingest_videos
_discover_ingest_sites = _discover_flow_support._discover_ingest_sites
_discover_ingest_set = _discover_flow_support._discover_ingest_set

_read_json_file = _topic_changes_support._read_json_file
_topic_change_history_path = _topic_changes_support._topic_change_history_path
_topic_diff_output_path = _topic_changes_support._topic_diff_output_path
_topic_trends_output_path = _topic_changes_support._topic_trends_output_path
_watch_alerts_output_path = _topic_changes_support._watch_alerts_output_path
_relative_library_path = _topic_changes_support._relative_library_path
_collect_topic_change_details = _topic_changes_support._collect_topic_change_details
_topic_change_snapshot = _topic_changes_support._topic_change_snapshot
_render_topic_diff_markdown = _topic_changes_support._render_topic_diff_markdown
_append_topic_change_history = _topic_changes_support._append_topic_change_history
_load_topic_change_history = _topic_changes_support._load_topic_change_history
_topic_trend_direction = _topic_changes_support._topic_trend_direction
_topic_trend_label = _topic_changes_support._topic_trend_label
_topic_watch_alert_lines = _topic_changes_support._topic_watch_alert_lines
_write_watch_alert_digest = _topic_changes_support._write_watch_alert_digest
_render_topic_trends_markdown = _topic_changes_support._render_topic_trends_markdown
_write_topic_change_briefing = _topic_changes_support._write_topic_change_briefing
_resolve_topic_diff_baseline = _topic_changes_support._resolve_topic_diff_baseline


# `app` (the top-level Typer instance + its did-you-mean group class) is defined
# in distill._app and imported at the top of this module, so the hundreds of
# `@app.command` decorators below attach to that same instance.


def _version_callback(value: bool) -> None:
    """Eager ``--version`` handler: print the version to stdout and exit 0.

    Eager so it works before any subcommand wiring or config load -- an agent
    or bug report can read the version without a configured environment.
    """
    if value:
        import typer as _typer

        _typer.echo(_get_version())
        raise _typer.Exit()


@app.callback()
def _default(
    ctx: typer.Context,
    debug: bool = typer.Option(False, "--debug", help="Enable DEBUG-level logging to console"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress human output"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON to stdout"),
    model: str = typer.Option("", "--model", "-m", help="Override model for all workloads"),
    cost_mode: str = typer.Option("", "--cost-mode", help="Override cost policy"),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the installed distill version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
):
    """Distill - YouTube channels to strategic intelligence."""
    from distill._logging import configure_logging

    # In --json mode, redirect all human/progress/diagnostic output to stderr so
    # stdout carries only the JSON envelope (commands write that envelope
    # directly to stdout). Called every invocation so a reused process resets
    # the stream rather than leaking a prior redirect. Supersedes the old
    # console.quiet approach, which dropped diagnostics entirely.
    effective_debug = _apply_output_mode(
        ctx,
        quiet=quiet,
        verbose=verbose,
        debug=debug,
        json_output=json_output,
        model=model,
    )
    _apply_cost_mode_override(cost_mode)

    try:
        ops_dir = get_config().library_dir / ".distill"
    except Exception:
        ops_dir = None
    configure_logging(debug=effective_debug, ops_dir=ops_dir)

    if ctx.invoked_subcommand is None:
        # Only clear the screen for an interactive terminal; clearing when output
        # is piped or captured (an agent shell, a loop) emits escape codes into
        # the captured stream.
        if sys.stdout.isatty():
            console.clear()
        show_banner(console)
        # Lazy import: the dashboard module imports helpers back from this
        # module, so importing it at module load would cycle.
        from distill.commands.dashboard import _show_dashboard

        _show_dashboard()


def get_model_override(ctx: typer.Context | None = None) -> str:
    """Get the --model override from the CLI context, if set."""
    if ctx and ctx.obj:
        return ctx.obj.get("model", "")
    return ""


def _resolve_video_channel_name(url: str, video_info) -> str:
    return _shared_resolve_video_channel_name(url, video_info, resolve_channel_name)


# ─── Power Commands ──────────────────────────────────────────────────


# ─── Library Management ───────────────────────────────────────────────


# ─── Browsing & Inspection ────────────────────────────────────────────
# `show`, `package-latest`, `synthesis`, `findings` (+ their `_show_payload` /
# `_emit_content_json` helpers) moved to commands/view.py (decomposition slice 4).


# ─── Processing ────────────────────────────────────────────────────────


# ─── Report Generation ─────────────────────────────────────────────────


# ─── Status & Doctor ──────────────────────────────────────────────────


concepts_app = typer.Typer(
    help=(
        "Concept and entity playbook for a topic.\n\n"
        "  distill concepts build <topic>            extract + merge playbook notes\n"
        "  distill concepts log <topic> <slug>       list a note's history snapshots\n"
        "  distill concepts diff <topic> <slug>      diff a note against its history\n"
        "  distill concepts rollback <topic> <slug> <timestamp>   restore a snapshot\n"
    ),
    rich_markup_mode="rich",
    no_args_is_help=True,
)
app.add_typer(concepts_app, name="concepts", rich_help_panel="Library")
# The `concepts build` command (and the log/diff/rollback recovery surface) live
# in commands/concepts.py and are attached to concepts_app via its register().


def main():
    """Entry point for the `distill` CLI command."""
    app()


if __name__ == "__main__":
    main()
