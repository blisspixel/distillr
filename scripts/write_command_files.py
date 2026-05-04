"""Write all command module files for the CLI restructure."""

import os

files = {
    "distill/commands/costs.py": '''\
"""Cost history command group.

Commands: distill costs
"""

import typer

from distill._cli_impl import costs as _costs_fn

__all__ = ["app"]

app = typer.Typer(help="Cost tracking and history.", rich_markup_mode="rich")
app.command(rich_help_panel="Maintain")(_costs_fn)
''',
    "distill/commands/doctor.py": '''\
"""Doctor, health, cleanup, and migration command group.

Commands: distill doctor, distill health, distill cleanup, distill migrate
"""

import typer

from distill._cli_impl import cleanup as _cleanup_fn
from distill._cli_impl import doctor as _doctor_fn
from distill._cli_impl import health as _health_fn
from distill._cli_impl import migrate as _migrate_fn

__all__ = ["app"]

app = typer.Typer(help="System health and maintenance.", rich_markup_mode="rich")
app.command(rich_help_panel="Maintain")(_doctor_fn)
app.command(rich_help_panel="Maintain")(_health_fn)
app.command(rich_help_panel="Maintain")(_cleanup_fn)
app.command(rich_help_panel="Maintain")(_migrate_fn)
''',
    "distill/commands/serve.py": '''\
"""Web dashboard server command group.

Commands: distill serve
"""

import typer

from distill._cli_impl import serve as _serve_fn

__all__ = ["app"]

app = typer.Typer(help="Local web dashboard.", rich_markup_mode="rich")
app.command(rich_help_panel="View")(_serve_fn)
''',
    "distill/commands/dashboard.py": '''\
"""Dashboard and status command group.

Commands: distill dashboard, distill status
"""

import typer

from distill._cli_impl import dashboard as _dashboard_fn
from distill._cli_impl import status as _status_fn

__all__ = ["app"]

app = typer.Typer(help="Dashboard and library status.", rich_markup_mode="rich")
app.command(rich_help_panel="Maintain")(_dashboard_fn)
app.command(rich_help_panel="Maintain")(_status_fn)
''',
    "distill/commands/latest.py": '''\
"""Latest, run, catch-up, reanalyze, channel, and video command group.

Commands: distill latest, distill run, distill catch-up, distill reanalyze,
          distill channel, distill video
"""

import typer

from distill._cli_impl import catch_up as _catch_up_fn
from distill._cli_impl import channel_cmd as _channel_cmd_fn
from distill._cli_impl import latest_cmd as _latest_cmd_fn
from distill._cli_impl import reanalyze as _reanalyze_fn
from distill._cli_impl import run as _run_fn
from distill._cli_impl import video as _video_fn

__all__ = ["app"]

app = typer.Typer(help="Content processing commands.", rich_markup_mode="rich")
app.command(name="latest", rich_help_panel="Discover")(_latest_cmd_fn)
app.command(rich_help_panel="Process")(_run_fn)
app.command(name="catch-up", rich_help_panel="Watch")(_catch_up_fn)
app.command(rich_help_panel="Maintain")(_reanalyze_fn)
app.command(name="channel", rich_help_panel="Process")(_channel_cmd_fn)
app.command(rich_help_panel="Process")(_video_fn)
''',
    "distill/commands/papers.py": '''\
"""Paper and corpus command group.

Commands: distill paper, distill papers, distill corpus
"""

import typer

from distill._cli_impl import corpus as _corpus_fn
from distill._cli_impl import paper as _paper_fn
from distill._cli_impl import papers as _papers_fn

__all__ = ["app"]

app = typer.Typer(help="Academic paper commands.", rich_markup_mode="rich")
app.command(rich_help_panel="Discover")(_paper_fn)
app.command(rich_help_panel="Discover")(_papers_fn)
app.command(rich_help_panel="Maintain")(_corpus_fn)
''',
    "distill/commands/site.py": '''\
"""Site crawling command group.

Commands: distill site, distill site-batch
"""

import typer

from distill._cli_impl import site_batch_cmd as _site_batch_cmd_fn
from distill._cli_impl import site_cmd as _site_cmd_fn

__all__ = ["app"]

app = typer.Typer(help="Website crawling and analysis.", rich_markup_mode="rich")
app.command(name="site", rich_help_panel="Discover")(_site_cmd_fn)
app.command(name="site-batch", rich_help_panel="Discover")(_site_batch_cmd_fn)
''',
    "distill/commands/synthesize.py": '''\
"""Synthesis command group.

Commands: distill synthesize, distill resynthesize
"""

import typer

from distill._cli_impl import resynthesize as _resynthesize_fn
from distill._cli_impl import synthesize_cmd as _synthesize_cmd_fn

__all__ = ["app"]

app = typer.Typer(help="Synthesis commands.", rich_markup_mode="rich")
app.command(name="synthesize", rich_help_panel="Discover")(_synthesize_cmd_fn)
app.command(rich_help_panel="Maintain")(_resynthesize_fn)
''',
    "distill/commands/research_brief.py": '''\
"""Research brief command group.

Commands: distill research-brief
"""

import typer

from distill._cli_impl import research_brief_cmd as _research_brief_cmd_fn

__all__ = ["app"]

app = typer.Typer(help="Research brief generation.", rich_markup_mode="rich")
app.command(name="research-brief", rich_help_panel="Discover")(_research_brief_cmd_fn)
''',
    "distill/commands/report.py": '''\
"""Report command group.

Commands: distill report, distill brief
"""

import typer

from distill._cli_impl import brief_cmd as _brief_cmd_fn
from distill._cli_impl import report as _report_fn

__all__ = ["app"]

app = typer.Typer(help="Report generation.", rich_markup_mode="rich")
app.command(rich_help_panel="Reports")(_report_fn)
app.command(name="brief", rich_help_panel="Discover")(_brief_cmd_fn)
''',
    "distill/commands/discover.py": '''\
"""Discovery command group.

Commands: distill discover, distill learn, distill explore, distill search
"""

import typer

from distill._cli_impl import discover as _discover_fn
from distill._cli_impl import explore_cmd as _explore_cmd_fn
from distill._cli_impl import learn_cmd as _learn_cmd_fn
from distill._cli_impl import search_cmd as _search_cmd_fn

__all__ = ["app"]

app = typer.Typer(help="Content discovery.", rich_markup_mode="rich")
app.command(rich_help_panel="Discover")(_discover_fn)
app.command(name="learn", rich_help_panel="Discover")(_learn_cmd_fn)
app.command(name="explore", rich_help_panel="Discover")(_explore_cmd_fn)
app.command(name="search", rich_help_panel="Discover")(_search_cmd_fn)
''',
    "distill/commands/watch.py": '''\
"""Watch and topic-watch command group.

Commands: distill watch *, distill topic-watch *, distill monitor, distill ramp-up
"""

import typer

from distill._cli_impl import monitor as _monitor_fn
from distill._cli_impl import ramp_up as _ramp_up_fn
from distill._cli_impl import topic_watch_add as _topic_watch_add_fn
from distill._cli_impl import topic_watch_budget as _topic_watch_budget_fn
from distill._cli_impl import topic_watch_cadence as _topic_watch_cadence_fn
from distill._cli_impl import topic_watch_days as _topic_watch_days_fn
from distill._cli_impl import topic_watch_default as _topic_watch_default_fn
from distill._cli_impl import topic_watch_pause as _topic_watch_pause_fn
from distill._cli_impl import topic_watch_ranking as _topic_watch_ranking_fn
from distill._cli_impl import topic_watch_remove as _topic_watch_remove_fn
from distill._cli_impl import topic_watch_resume as _topic_watch_resume_fn
from distill._cli_impl import topic_watch_run as _topic_watch_run_fn
from distill._cli_impl import watch_add as _watch_add_fn
from distill._cli_impl import watch_days as _watch_days_fn
from distill._cli_impl import watch_default as _watch_default_fn
from distill._cli_impl import watch_instructions as _watch_instructions_fn
from distill._cli_impl import watch_remove as _watch_remove_fn

__all__ = ["app", "topic_watch_app", "watch_app"]

# Channel watch sub-app
watch_app = typer.Typer(
    help="Manage your channel watch list",
    invoke_without_command=True,
    rich_markup_mode="rich",
)
watch_app.callback()(_watch_default_fn)
watch_app.command("add")(_watch_add_fn)
watch_app.command("remove")(_watch_remove_fn)
watch_app.command("instructions")(_watch_instructions_fn)
watch_app.command("days")(_watch_days_fn)

# Topic watch sub-app
topic_watch_app = typer.Typer(
    help="Manage your recurring topic watches",
    invoke_without_command=True,
    rich_markup_mode="rich",
)
topic_watch_app.callback()(_topic_watch_default_fn)
topic_watch_app.command("add")(_topic_watch_add_fn)
topic_watch_app.command("remove")(_topic_watch_remove_fn)
topic_watch_app.command("days")(_topic_watch_days_fn)
topic_watch_app.command("cadence")(_topic_watch_cadence_fn)
topic_watch_app.command("ranking")(_topic_watch_ranking_fn)
topic_watch_app.command("budget")(_topic_watch_budget_fn)
topic_watch_app.command("pause")(_topic_watch_pause_fn)
topic_watch_app.command("resume")(_topic_watch_resume_fn)
topic_watch_app.command("run")(_topic_watch_run_fn)

# Top-level commands that belong to the watch domain
app = typer.Typer(help="Watch and monitoring commands.", rich_markup_mode="rich")
app.command(name="monitor", rich_help_panel="Discover")(_monitor_fn)
app.command(name="ramp-up", rich_help_panel="Discover")(_ramp_up_fn)
''',
    "distill/commands/topics.py": '''\
"""Topic command group.

Commands: distill topic create, distill topic preview, distill topic update,
          distill topic brief, distill topic report, distill topic show,
          distill topic export, distill topic watch
"""

import typer

from distill._cli_impl import topic_brief as _topic_brief_fn
from distill._cli_impl import topic_create as _topic_create_fn
from distill._cli_impl import topic_export as _topic_export_fn
from distill._cli_impl import topic_preview as _topic_preview_fn
from distill._cli_impl import topic_report as _topic_report_fn
from distill._cli_impl import topic_show as _topic_show_fn
from distill._cli_impl import topic_update as _topic_update_fn
from distill._cli_impl import topic_watch as _topic_watch_fn

__all__ = ["app"]

app = typer.Typer(
    help=(
        "Topic-first workflows.\\n\\n"
        "Recommended flow:\\n"
        "  distill topic create \\"topic here\\" --videos 10 --papers 10\\n"
        "  distill topic update <topic>\\n"
        "  distill topic brief <topic>\\n"
        "  distill topic report <topic>\\n"
    ),
    rich_markup_mode="rich",
)
app.command("create")(_topic_create_fn)
app.command("preview")(_topic_preview_fn)
app.command("update")(_topic_update_fn)
app.command("brief")(_topic_brief_fn)
app.command("report")(_topic_report_fn)
app.command("show")(_topic_show_fn)
app.command("export")(_topic_export_fn)
app.command("watch")(_topic_watch_fn)
''',
    "distill/commands/library.py": '''\
"""Library management command group.

Commands: distill add, distill remove, distill library, distill videos,
          distill show, distill package-latest, distill synthesis,
          distill findings, distill diff, distill trends, distill open,
          distill export
"""

import typer

from distill._cli_impl import add as _add_fn
from distill._cli_impl import diff as _diff_fn
from distill._cli_impl import export as _export_fn
from distill._cli_impl import findings as _findings_fn
from distill._cli_impl import library_cmd as _library_cmd_fn
from distill._cli_impl import open_cmd as _open_cmd_fn
from distill._cli_impl import package_latest as _package_latest_fn
from distill._cli_impl import remove as _remove_fn
from distill._cli_impl import show as _show_fn
from distill._cli_impl import synthesis as _synthesis_fn
from distill._cli_impl import trends as _trends_fn
from distill._cli_impl import videos as _videos_fn

__all__ = ["app"]

app = typer.Typer(help="Library management.", rich_markup_mode="rich")
app.command(rich_help_panel="Library")(_add_fn)
app.command(rich_help_panel="Library")(_remove_fn)
app.command(name="library", rich_help_panel="Library")(_library_cmd_fn)
app.command(rich_help_panel="Library")(_videos_fn)
app.command(rich_help_panel="View")(_show_fn)
app.command(name="package-latest", rich_help_panel="View")(_package_latest_fn)
app.command(rich_help_panel="View")(_synthesis_fn)
app.command(rich_help_panel="View")(_findings_fn)
app.command(rich_help_panel="View")(_diff_fn)
app.command(rich_help_panel="View")(_trends_fn)
app.command(name="open", rich_help_panel="Maintain")(_open_cmd_fn)
app.command(rich_help_panel="Reports")(_export_fn)
''',
}

for path, content in files.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    size = os.path.getsize(path)
    print(f"  {path}: {size} bytes")

print(f"\nWrote {len(files)} command files")
