"""Topic workflow command group.

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
        "Topic-first workflows.\n\n"
        "Recommended flow:\n"
        '  distill topic create "topic here" --videos 10 --papers 10\n'
        "  distill topic update <topic>\n"
        "  distill topic brief <topic>\n"
        "  distill topic report <topic>\n"
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
