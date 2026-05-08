"""Watch list and topic-watch command groups.

Commands: distill watch *, distill topic-watch *
"""

import typer

from distill.commands._logic import topic_watch_add as _topic_watch_add_fn
from distill.commands._logic import topic_watch_budget as _topic_watch_budget_fn
from distill.commands._logic import topic_watch_cadence as _topic_watch_cadence_fn
from distill.commands._logic import topic_watch_days as _topic_watch_days_fn
from distill.commands._logic import topic_watch_default as _topic_watch_default_fn
from distill.commands._logic import topic_watch_pause as _topic_watch_pause_fn
from distill.commands._logic import topic_watch_ranking as _topic_watch_ranking_fn
from distill.commands._logic import topic_watch_remove as _topic_watch_remove_fn
from distill.commands._logic import topic_watch_resume as _topic_watch_resume_fn
from distill.commands._logic import topic_watch_run as _topic_watch_run_fn
from distill.commands._logic import watch_add as _watch_add_fn
from distill.commands._logic import watch_days as _watch_days_fn
from distill.commands._logic import watch_default as _watch_default_fn
from distill.commands._logic import watch_instructions as _watch_instructions_fn
from distill.commands._logic import watch_remove as _watch_remove_fn

__all__ = ["topic_watch_app", "watch_app"]

# ─── Channel Watch ───────────────────────────────────────────────────

watch_app = typer.Typer(
    help="Manage your channel watch list.",
    invoke_without_command=True,
    rich_markup_mode="rich",
)
watch_app.callback()(_watch_default_fn)
watch_app.command("add")(_watch_add_fn)
watch_app.command("remove")(_watch_remove_fn)
watch_app.command("instructions")(_watch_instructions_fn)
watch_app.command("days")(_watch_days_fn)

# ─── Topic Watch ─────────────────────────────────────────────────────

topic_watch_app = typer.Typer(
    help="Manage your recurring topic watches.",
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
