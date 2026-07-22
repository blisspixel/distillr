"""Distill CLI - thin wiring module.

This module is the public entry point for the ``distill`` command.
Command groups live in focused ``distill.commands.*`` modules, while
``distill._cli_impl`` preserves private compatibility exports.

The ``app`` and ``main()`` exported here are the canonical runtime
instances used by ``pyproject.toml [project.scripts]``.

Implementation note: we re-export every public and private name from
``_cli_impl`` so that existing test code that monkeypatches attributes
on ``distill.cli`` (e.g. ``monkeypatch.setattr(cli, "resolve_channel_name", ...)``)
continues to work without changes.  This shim will shrink further once
the test suite patches the canonical module paths directly.
"""

from __future__ import annotations

import distill._bootstrap  # noqa: F401 - UTF-8 stdio side-effect

# Re-export everything from _cli_impl so tests that monkeypatch
# attributes on ``distill.cli`` keep working.
from distill._cli_impl import *  # noqa: F403
from distill._cli_impl import (  # noqa: F401 - private names needed by tests
    _append_topic_change_history,
    _apply_ranked_channel_cap,
    _auto_skeptical_mode,
    _collect_topic_change_details,
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
    _load_topic_change_history,
    _preflight,
    _preview_learning_selection,
    _process_learning_selection,
    _process_video,
    _RankedDiscoverItem,
    _read_json_file,
    _render_topic_diff_markdown,
    _render_topic_trends_markdown,
    _replace_case_insensitive,
    _resolve_topic_diff_baseline,
    _run_learning_command,
    _run_scope_report,
    _select_learning_videos,
    _strip_intent_terms,
    _strip_noise_terms,
    _topic_diff_output_path,
    _topic_trend_direction,
    _topic_trends_output_path,
    _topic_watch_alert_lines,
    _truncate_channel_list,
    _watch_alerts_output_path,
    _window_label,
    _write_topic_change_briefing,
    _write_watch_alert_digest,
    app,
    console,
    get_config,
)
from distill.cli_shared import format_date as _format_date  # noqa: F401
from distill.commands import _site_ingest as _site_ingest_support

# _file_link's canonical home is _helpers; _logic no longer imports it, so
# re-export from the source to preserve cli._file_link for tests.
from distill.commands._helpers import _file_link  # noqa: F401

# Register commands defined in dedicated modules. The import side-effect
# attaches each command to ``app``.
from distill.commands.ask import register as _register_ask
from distill.commands.audit import register as _register_audit
from distill.commands.claude_md import register as _register_claude_md
from distill.commands.concepts import concepts_app
from distill.commands.concepts import register as _register_concepts_recovery

# Home-screen/dashboard renderers moved to commands/dashboard.py; re-export
# _show_dashboard so tests patching cli._show_dashboard keep working.
from distill.commands.dashboard import _show_dashboard  # noqa: F401
from distill.commands.discover import register as _register_discover
from distill.commands.doctor import register as _register_doctor
from distill.commands.eval import register as _register_eval
from distill.commands.ingest import register as _register_ingest
from distill.commands.init import register as _register_init
from distill.commands.intent import register as _register_intent
from distill.commands.learn import register as _register_learn
from distill.commands.maintain import register as _register_maintain
from distill.commands.okf import okf_app  # noqa: F401
from distill.commands.okf import register as _register_okf
from distill.commands.papers import register as _register_papers
from distill.commands.process import register as _register_process
from distill.commands.profile import profile_app  # noqa: F401
from distill.commands.profile import register as _register_profile
from distill.commands.provider import register as _register_provider
from distill.commands.reports import register as _register_reports
from distill.commands.reprocess import register as _register_reprocess
from distill.commands.skill import skill_app
from distill.commands.topic import (  # noqa: F401
    _collect_topic_bundle_files,
    _export_topic_bundle,
    _load_topic_profile,
    _render_topic_summary,
    _resolve_topic_workflow_config,
    _run_topic_workflow,
    _save_topic_profile,
    _topic_bundle_manifest,
    _topic_exists,
    _topic_profile_path,
    topic_app,
)
from distill.commands.topic import (
    register as _register_topic,
)
from distill.commands.topic_watch import register as _register_topic_watch
from distill.commands.topic_watch import topic_watch_app  # noqa: F401
from distill.commands.update import register as _register_update
from distill.commands.view import register as _register_view
from distill.commands.watch import register as _register_watch
from distill.commands.worker import worker_app
from distill.pipeline.costs import CostTracker  # noqa: F401

_content_hash = _site_ingest_support.content_hash
_process_site_seed = _site_ingest_support.process_site_seed
_site_section_change_summary = _site_ingest_support.site_section_change_summary

_register_ingest(app)
app.add_typer(concepts_app, name="concepts", rich_help_panel="Library")
_register_concepts_recovery(concepts_app)
_register_claude_md(app)
_register_audit(app)
_register_ask(app)
_register_update(app)
_register_init(app)
_register_intent(app)
_register_maintain(app)
_register_provider(app)
_register_doctor(app)
_register_eval(app)
_register_reprocess(app)
_register_okf(app)
_register_topic(app)
_register_reports(app)
_register_discover(app)
_register_learn(app)
_register_papers(app)
_register_profile(app)
_register_process(app)
_register_view(app)
_register_topic_watch(app)
_register_watch(app)
app.add_typer(worker_app, name="worker", rich_help_panel="Operations")
app.add_typer(skill_app, name="skill", rich_help_panel="Operations")

__all__ = ["app", "main"]


def _mark_cli_exit_outcome(code: object) -> None:
    """Preserve the public process-status taxonomy in local run telemetry."""
    from distill.commands._json import ExitCode
    from distill.llm.run_context import mark_current_run_outcome

    exit_outcomes = {
        int(ExitCode.RUNTIME_ERROR): "error",
        int(ExitCode.USAGE_ERROR): "usage_error",
        int(ExitCode.CONFIG_ERROR): "config_error",
        int(ExitCode.NETWORK_ERROR): "network_error",
        int(ExitCode.NOT_FOUND): "not_found",
        int(ExitCode.BUDGET_EXCEEDED): "budget_exceeded",
    }
    if code is None or (isinstance(code, int) and code == int(ExitCode.SUCCESS)):
        return
    outcome = exit_outcomes.get(code, "error") if isinstance(code, int) else "error"
    mark_current_run_outcome(outcome)


def _handle_provider_cli_error(exc: Exception, message: str) -> int:
    """Render one recognized provider failure and return its semantic status."""
    from rich.markup import escape

    from distill.commands._json import (
        handle_cli_error,
        json_mode_active,
        map_exception_to_exit_code,
    )

    if json_mode_active():
        return handle_cli_error(exc, json_mode=True)
    console.print(f"\n[red]{escape(message)}[/red]")
    return int(map_exception_to_exit_code(exc))


def main() -> None:
    """Entry point for the ``distill`` CLI command.

    Wraps the Typer app so that *expected* provider failures (credits exhausted,
    bad key, rate limit) print a clean one-line message instead of a full
    traceback. Unrecognized errors propagate unchanged.
    """
    from distill.commands._json import (
        ExitCode,
        emit_json,
        json_mode_active,
    )
    from distill.llm.cost_policy import CostPolicyError
    from distill.llm.errors import describe_provider_error
    from distill.llm.run_context import mark_current_run_outcome, run_scope
    from distill.pipeline.costs import (
        BudgetExceededError,
        ProjectedBudgetExceededError,
    )

    app.pretty_exceptions_enable = False
    with run_scope(invocation_type="cli", command="cli"):
        try:
            _run_app_with_terminal_receipt()
        except SystemExit as exc:
            _mark_cli_exit_outcome(exc.code)
            raise
        except CostPolicyError as exc:
            mark_current_run_outcome("refused")
            if json_mode_active():
                emit_json({"reason": "cost_policy_blocked"}, error=str(exc))
            else:
                console.print(f"\n[red]{exc}[/red]")
            raise SystemExit(int(ExitCode.CONFIG_ERROR)) from exc
        except BudgetExceededError as exc:
            mark_current_run_outcome("budget_exceeded")
            if json_mode_active():
                payload: dict[str, object] = {
                    "reason": "budget_exceeded",
                    "spent_usd": round(exc.spent, 6),
                    "budget_usd": round(exc.budget, 6),
                }
                if isinstance(exc, ProjectedBudgetExceededError):
                    payload["projected"] = True
                    payload["projected_usd"] = round(exc.projected, 6)
                emit_json(payload, error=str(exc))
            else:
                console.print(f"\n[red]Budget exceeded: {exc}[/red]")
            raise SystemExit(int(ExitCode.BUDGET_EXCEEDED)) from exc
        except Exception as exc:
            message = describe_provider_error(exc)
            if message is None:
                raise
            exit_code = _handle_provider_cli_error(exc, message)
            _mark_cli_exit_outcome(exit_code)
            raise SystemExit(exit_code) from exc


def _run_app_with_terminal_receipt() -> None:
    """Invoke the CLI and close a successful profile child's receipt contract."""

    from distill.pipeline.costs import ensure_terminal_profile_receipt

    completed_successfully = False
    try:
        app()
        completed_successfully = True
    except SystemExit as exc:
        completed_successfully = exc.code in (None, 0)
        raise
    finally:
        if completed_successfully:
            ensure_terminal_profile_receipt()
