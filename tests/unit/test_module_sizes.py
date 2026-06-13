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
    # migrate + corpus -> commands/maintain.py (Maintain slice 5): 6983 -> 6884.
    "distill/commands/_logic.py": 6884,
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
