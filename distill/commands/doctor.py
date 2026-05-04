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
