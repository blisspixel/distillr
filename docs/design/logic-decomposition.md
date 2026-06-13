# Decomposing `_logic.py` (design / Frame)

> Status: plan. Remediation #1 from [`how-we-build.md`](how-we-build.md). This is
> the architectural-change case the operating model says gets a design doc before
> code. It executes as many small green PRs across sessions, not one big bang.

## Problem & North-Star tie

`distill/commands/_logic.py` is **9,373 lines / 155 functions** — 9× the 1000-line
ceiling, 21× the next file, and a direct violation of the ROADMAP's "one command
group per file" target. It earns the *feature spine* (not just a harden pass)
because **agent-context-fit is legibility for the dominant reader**: a 9k-line
module can't be loaded or reasoned about in an agent's context window, and it's
the single worst offender. Goal: every command group in its own
`distill/commands/<group>.py`, `_logic.py` shrinks to ≤1000 then disappears as a
named module, the size-ratchet allowlist entry drops to zero.

## The hazard (why naïve "move the function" false-greens)

There are **76 `from distill.commands._logic import <symbol>`** sites across
`distill/` and `tests/`, plus tests and MCP tools that patch by **string path**
(`monkeypatch.setattr("distill.commands._logic._process_site_seed", …)`,
`patch("distill.commands._logic._doctor_validate_key", …)`). If a function is
physically moved to `commands/<group>.py` but a test still patches
`distill.commands._logic.<fn>`, the patch silently binds a **stale namespace**:
the production call site resolves the real function from the new module, the test
patches nothing, and **the test passes while testing nothing** — the exact
"looks correct, isn't" class the charter warns about, hidden inside the
remediation.

## The safe procedure (per command group)

The target pattern already exists: `commands/update.py` / `audit.py` are
full implementations with a `register(app)` (or `@app.command`) entry, *not* thin
wrappers over `_logic`. Migrate each old monolith group into that shape:

1. **Move** the command function(s) + their *group-private* helpers into
   `distill/commands/<group>.py`. Shared helpers stay in `_logic` (or move to
   `_helpers.py`) and are imported back — the facade points *into* the new module,
   shared utilities still flow *from* the foundation.
2. **Facade:** `_logic.py` re-exports the moved names
   (`from distill.commands.<group> import <names>`) so every existing
   `from distill.commands._logic import <name>` keeps working *unchanged* during
   migration.
3. **Repoint** every call site **and every patch string** to the new path — in
   the **same PR**. This is the load-bearing step.
4. **Grep gate (pre-merge, blocking):** `grep -rn "distill.commands._logic" tests/ distill/`
   must not reference a symbol that has moved. A stale patch string is the failure
   mode; the grep is how we catch the false-green before it ships. (A green build
   with a stale patch string is *not* sufficient evidence.)
5. **Delete the facade entry** once all references use the new path; **lower the
   `test_module_sizes.py` allowlist number** by the lines removed.

When a group is large or its patch strings are many, split into two PRs:
(a) move + facade (green, nothing repointed yet), (b) repoint + delete facade
(green). Never "move + repoint in one careless pass."

## Slice ordering (lowest-coupling first)

Migrate by `rich_help_panel` group, easiest first to prove the pattern, hardest
(the discover/process pipeline core, which owns the most shared helpers) last:

1. **View** (`library`, `videos`, `show`, `synthesis`, `findings`, `package-latest`)
   — pure reads; the `--json` payload helpers added in 0.14 already live near
   here. Best first slice: highest value (agent-facing reads), lowest risk.
2. **Maintain** (`costs`, `doctor`/`health`, `cleanup`, `migrate`, `open`, `alerts`)
   — mostly self-contained; `costs`/`doctor` already have `ctx`-based `--json`.
3. **Watch** (`catch-up`, watch/topic-watch) and **Reports** (`report`,
   `research-brief` wiring) — moderate coupling.
4. **Discover / Process** (`discover`, `papers`, `latest`, `learn`, `site`,
   `site-batch`, `run`, `channel`) — the core pipeline + the bulk of shared
   helpers; migrate last, possibly extracting shared helpers to `_helpers.py`
   first.

## Definition of done (per slice)

Green CI (incl. the grep gate and module-size ratchet); the moved group's tests
patch the new path; `_logic.py` line count drops and the allowlist number drops
with it; no behavior change (pure move). The whole effort is done when
`_logic.py` is gone and the allowlist is empty.

## Not in scope

No behavior changes, no signature changes, no "while I'm here" refactors inside a
move PR — a move PR is a *pure relocation* so the diff is reviewable and any test
failure is unambiguously a wiring problem, not a logic regression.
