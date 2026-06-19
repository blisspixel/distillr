"""Module-size ratchet (how-we-build.md §9).

No Python module in ``distill/`` exceeds the 1000-line hard ceiling, except a
shrinking allowlist whose recorded sizes may **only decrease**. Ruff has no
per-file line cap, so this pytest is the enforcement and it runs in the same
green suite the whole flow is built around.

There are currently no allowlisted modules. If a temporary exception is ever
needed, it must be tracked here as shrinking debt and removed once the file
drops to <=1000 lines.
"""

from __future__ import annotations

import pathlib

import distill

HARD_CAP = 1000

# path (repo-relative, posix) -> max allowed lines. Must only decrease.
ALLOWLIST: dict[str, int] = {}

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
