"""Persisted topic goals: the durable half of the goal-file watch hook.

A goal-driven `distill discover` run establishes a goal<->topic association
that should outlive the invocation -- that is what lets goal-driven topics
refresh on the same schedule as keyword topics. The goal *text* is persisted
(so a moved or deleted goal file doesn't break refresh) along with the
original file path and site-seed file for the exact replay command.
`distill catch-up` surfaces the refresh commands at the end of every run:
spend surfaced, never auto-committed, consistent with the scheduling
recipes' preview-on-purpose philosophy (re-runs are convergent -- the
corpus-aware rerank drops already-ingested candidates, so a refresh only
surfaces what's new).
"""

from __future__ import annotations

import json
from pathlib import Path

from distill.library.paths import atomic_write_text

__all__ = ["goal_refresh_command", "load_topic_goals", "save_topic_goal"]

_GOALS_FILENAME = "goals.json"


def _goals_path(library_dir: Path) -> Path:
    return library_dir / ".distill" / _GOALS_FILENAME


def load_topic_goals(library_dir: Path) -> dict[str, dict]:
    """All persisted goals, keyed by topic. Corrupt files read as empty."""
    path = _goals_path(library_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_topic_goal(
    library_dir: Path,
    topic: str,
    goal: str,
    *,
    goal_file: str = "",
    site_seeds: str = "",
    trusted_sites: list[str] | None = None,
    now_iso: str = "",
) -> None:
    """Persist (or update) one topic's goal association."""
    if not topic or not goal.strip():
        return
    goals = load_topic_goals(library_dir)
    goals[topic] = {
        "goal": goal.strip(),
        "goal_file": goal_file,
        "site_seeds": site_seeds,
        "trusted_sites": trusted_sites or [],
        "saved_at": now_iso,
    }
    path = _goals_path(library_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: a crash mid-write must not corrupt the whole goals file -- the
    # corrupt-file recovery path reads {} and would silently drop every goal.
    atomic_write_text(path, json.dumps(goals, indent=2))


def _quoted(path_str: str) -> str:
    """Quote a path argument for the printed command when it needs it."""
    if any(ch.isspace() for ch in path_str):
        return '"' + path_str.replace('"', "'") + '"'
    return path_str


def goal_refresh_command(topic: str, entry: dict) -> str:
    """The exact preview command that refreshes this topic against its goal.

    Printed for an operator to run, never executed by distill itself; paths
    with whitespace are quoted so the printed line is copy-paste correct.
    """
    goal_file = str(entry.get("goal_file", "") or "")
    if goal_file:
        cmd = f"distill discover --goal-file {_quoted(goal_file)} --topic {topic} --preview"
    else:
        headline = str(entry.get("goal", "")).splitlines()[0][:120].replace('"', "'")
        cmd = f'distill discover "{headline}" --topic {topic} --preview'
    site_seeds = str(entry.get("site_seeds", "") or "")
    if site_seeds:
        cmd += f" --site-seeds {_quoted(site_seeds)}"
    trusted_sites = entry.get("trusted_sites", []) or []
    if isinstance(trusted_sites, str):
        trusted_sites = [trusted_sites]
    for source in trusted_sites:
        source_text = str(source or "")
        if source_text:
            cmd += f" --trusted-site {_quoted(source_text)}"
    return cmd
