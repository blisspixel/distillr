"""Module-size ratchet (how-we-build.md §9).

No Python module in ``distill/`` exceeds the 1000-line hard ceiling, except a
shrinking allowlist whose recorded sizes may **only decrease**. Ruff has no
per-file line cap, so this pytest is the enforcement and it runs in the same
green suite the whole flow is built around.

The sole current resident is the ``_logic.py`` monolith, tracked for
decomposition (how-we-build.md remediation #1). A PR may *lower* its number as
the file shrinks, never raise it; new >1000-line files are rejected outright;
and once an allowlisted file drops to <=1000 its entry must be removed.
"""

from __future__ import annotations

import pathlib

import distill

HARD_CAP = 1000

# path (repo-relative, posix) -> max allowed lines. MUST ONLY DECREASE.
ALLOWLIST: dict[str, int] = {
    # Decomposition in progress (how-we-build.md remediation #1); ratchet down
    # with each extracted slice. get_config (slice 0): 9373 -> 9368;
    # _resolve_topic_for_channel + _file_link (slice 1): 9368 -> 9331;
    # library command -> commands/view.py (slice 2): 9331 -> 9213;
    # videos command -> commands/view.py (slice 3): 9213 -> 9077;
    # show/package-latest/synthesis/findings -> view.py (slice 4): 9077 -> 8664;
    # app construction -> distill/_app.py (+ did-you-mean group): 8664 -> 8653;
    # costs + cleanup -> commands/maintain.py (Maintain slice 1): 8653 -> 8353;
    # open + alerts -> commands/maintain.py (Maintain slice 2): 8353 -> 8202;
    # doctor check helpers -> distill/doctor/checks.py (slice 1a): 8202 -> 8093
    # (net of the re-import block the doctor command still needs);
    # doctor + health commands -> commands/doctor.py (slice 1b): 8093 -> 7346;
    # status -> commands/maintain.py (Maintain slice 3): 7346 -> 7201;
    # eval + ollama-model helpers -> commands/eval.py (Maintain slice 4): 7201 -> 6983;
    # migrate + corpus -> commands/maintain.py (Maintain slice 5): 6983 -> 6884;
    # dashboard + serve -> commands/maintain.py (Maintain slice 6): 6884 -> 6845;
    # resynthesize + reanalyze -> commands/reprocess.py (Maintain slice 7): 6845 -> 6483;
    # report + export -> commands/reports.py (Reports slice): 6483 -> 6245;
    # _preflight + _invoke_command -> _helpers.py (Phase 2 foundation): 6245 -> 6203;
    # _resolve_intent -> _helpers.py (Phase 2 foundation): 6203 -> 6192;
    # search + explore -> commands/discover.py (Discover slice 1): 6192 -> 6103;
    # research-brief -> commands/discover.py (Discover slice 2): 6103 -> 6010;
    # learn + brief -> commands/discover.py (Discover slice 3): 6010 -> 5893;
    # latest -> commands/discover.py (Discover slice 4): 5893 -> 5741;
    # paper + papers -> commands/papers.py (Discover slice 5): 5741 -> 5502;
    # video + channel + run -> commands/process.py (Process slice): 5502 -> 4958;
    # synthesize + monitor + ramp-up + site + site-batch -> commands/discover.py
    # (Discover slice 6): 4958 -> 4507;
    # discover -> commands/discover.py (Discover slice 7): 4507 -> 4067
    # (learning family split out to commands/learn.py to keep both under the cap);
    # watch sub-app + catch-up -> commands/watch.py (Watch slice): 4067 -> 3672.
    # diff + trends + add + remove -> commands/view.py (View slice): 3672 -> 3478.
    # intent sub-app -> commands/intent.py (Library slice): 3478 -> 3392.
    # concepts build command -> commands/concepts.py (Library slice): 3392 -> 3316.
    # _validate_learning_options wrapper eliminated; consumers point at
    # commands/_learning_flow directly (Phase 2 foundation): 3316 -> 3304.
    # _detect_ramp_source (pure structural dispatch) -> _helpers.py;
    # discover.py repointed (Phase 2 foundation): 3304 -> 3290.
    # home-screen + HTML dashboard renderers (_show_dashboard,
    # _render_dashboard_html, _dashboard_snapshot, _dashboard_metric,
    # _build_start_here_table, _show_first_run_home) -> commands/dashboard.py;
    # _default lazy-imports it, maintain/cli repointed (Dashboard slice):
    # 3290 -> 2644.
    # topic-watch naming/ranking helpers (_topic_watch_name,
    # _normalize_topic_watch_ranking_mode, _topic_watch_ranking_strategy) ->
    # commands/_topic_watch.py support module; dashboard/discover repointed
    # (Phase 2 foundation): 2644 -> 2612.
    # topic-watch sub-app -> commands/topic_watch.py (Watch slice): 2612 -> 2210.
    # shared verify/lens/completion/source-rigor helpers -> support modules:
    # 1616 -> 1512.
    # discover ingest helpers -> commands/_discover_ingest.py: 1512 -> 1445.
    # output-mode setup -> commands/_helpers.py: 1445 -> 1444.
    # watch-owned display helpers -> commands/watch.py: 1444 -> 1355.
    "distill/commands/_logic.py": 1355,
}

_DISTILL_DIR = pathlib.Path(distill.__file__).resolve().parent
_REPO_ROOT = _DISTILL_DIR.parent


def _line_count(path: pathlib.Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_no_module_exceeds_cap_except_shrinking_allowlist():
    offenders: list[str] = []
    for path in sorted(_DISTILL_DIR.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        n = _line_count(path)
        cap = ALLOWLIST.get(rel, HARD_CAP)
        if n > cap:
            offenders.append(f"{rel}: {n} lines > {cap}")
    assert not offenders, (
        "module-size cap exceeded (split the file, or — only if justified — "
        "raise the allowlist, which is up-only debt):\n" + "\n".join(offenders)
    )


def test_allowlist_is_not_stale():
    """Allowlist hygiene: every entry must still exist and still need the
    exemption. When a file is decomposed below the hard cap, its entry must be
    deleted — that is the ratchet reaching its endpoint."""
    for rel, cap in ALLOWLIST.items():
        path = _REPO_ROOT / rel
        assert path.exists(), f"allowlist references a missing file: {rel}"
        n = _line_count(path)
        assert n > HARD_CAP, f"{rel} is now {n} <= {HARD_CAP} lines; remove it from ALLOWLIST"
        assert n <= cap, f"{rel} grew to {n} > allowlisted {cap}; the ratchet is up-only"
