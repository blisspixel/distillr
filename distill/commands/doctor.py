"""Doctor, health, cleanup, and migration command group.

Commands: distill doctor, distill health, distill cleanup, distill migrate
"""

import typer

from distill.commands._logic import cleanup as _cleanup_fn
from distill.commands._logic import doctor as _doctor_fn
from distill.commands._logic import health as _health_fn
from distill.commands._logic import migrate as _migrate_fn

__all__ = ["app"]

app = typer.Typer(help="System health and maintenance.", rich_markup_mode="rich")
app.command(rich_help_panel="Maintain")(_doctor_fn)
app.command(rich_help_panel="Maintain")(_health_fn)
app.command(rich_help_panel="Maintain")(_cleanup_fn)
app.command(rich_help_panel="Maintain")(_migrate_fn)
