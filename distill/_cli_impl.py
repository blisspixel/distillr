"""CLI compatibility exports for private legacy imports.

Command implementations live in focused ``distill.commands`` modules. This
module preserves the private symbols still imported by ``distill.cli`` and older
test code while the public runtime entry stays wiring-only.
"""

import os as os  # compatibility export

import distill.pipeline.discovery as _discover_support
from distill._app import app
from distill.cli_shared import (
    resolve_video_channel_name as _shared_resolve_video_channel_name,
)
from distill.commands import _discover_flow as _discover_flow_support
from distill.commands import _learning as _learning_support
from distill.commands import _topic_changes as _topic_changes_support
from distill.commands._helpers import (
    _apply_verify_override,  # noqa: F401 - compatibility export
    _complete_topic_watch_names,  # noqa: F401 - compatibility export
    _complete_topics,  # noqa: F401 - compatibility export
    _complete_watched_channels,  # noqa: F401 - compatibility export
    _invoke_command,  # noqa: F401 - compatibility export
    _persist_lens,  # noqa: F401 - compatibility export
    _preflight,  # noqa: F401 - compatibility export
    _resolve_intent,  # noqa: F401 - compatibility export
    _truncate_channel_list,  # noqa: F401 - compatibility export
    get_config,  # noqa: F401 - compatibility export
)
from distill.commands._helpers import (
    process_video as _process_video,  # noqa: F401 - compatibility export
)
from distill.commands._helpers import (
    run_scope_report as _run_scope_report,  # noqa: F401 - compatibility export
)
from distill.commands.concepts import concepts_app  # noqa: F401 - compatibility export
from distill.commands.root import (  # noqa: F401 - compatibility exports
    _default,
    _version_callback,
    console,
    get_model_override,
    get_provider_override,
    show_banner,
)
from distill.ingestors.youtube.discovery import resolve_channel_name
from distill.library import Library  # noqa: F401 - compatibility export

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
_topic_trends_output_path = _topic_changes_support.topic_trends_output_path
_watch_alerts_output_path = _topic_changes_support.watch_alerts_output_path
_relative_library_path = _topic_changes_support._relative_library_path
_collect_topic_change_details = _topic_changes_support._collect_topic_change_details
_topic_change_snapshot = _topic_changes_support.topic_change_snapshot
_render_topic_diff_markdown = _topic_changes_support._render_topic_diff_markdown
_append_topic_change_history = _topic_changes_support._append_topic_change_history
_load_topic_change_history = _topic_changes_support._load_topic_change_history
_topic_trend_direction = _topic_changes_support._topic_trend_direction
_topic_trend_label = _topic_changes_support._topic_trend_label
_topic_watch_alert_lines = _topic_changes_support._topic_watch_alert_lines
_write_watch_alert_digest = _topic_changes_support._write_watch_alert_digest
_render_topic_trends_markdown = _topic_changes_support.render_topic_trends_markdown
_write_topic_change_briefing = _topic_changes_support._write_topic_change_briefing
_resolve_topic_diff_baseline = _topic_changes_support.resolve_topic_diff_baseline


def _resolve_video_channel_name(url: str, video_info) -> str:
    return _shared_resolve_video_channel_name(url, video_info, resolve_channel_name)


def main() -> None:
    """Entry point for callers that still import ``distill._cli_impl``."""
    app()


if __name__ == "__main__":
    main()
