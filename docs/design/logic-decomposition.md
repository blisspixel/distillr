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

## Phase 2: the coupled core (status + plan)

**Phase 1 is done.** Every cleanly-separable group is out: View
(`commands/view.py`), the whole Maintain panel (`commands/maintain.py` +
`commands/eval.py` + `commands/reprocess.py`), doctor/health
(`commands/doctor.py` + the check helpers in `distill/doctor/checks.py`), Reports
(`commands/reports.py`), and the top-level app + did-you-mean group
(`distill/_app.py`). `_logic.py` went 9,373 → ~6,245 lines; 13 dead scaffold
modules were deleted along the way. The size ratchet's allowlist tracked every
step down.

**What remains is one tightly-coupled cluster**, which is why the slice ordering
put it last. The commands: Discover (`discover`, `papers`, `paper`, `latest`,
`learn`, `search`, `explore`, `brief`, `research-brief`, `monitor`), Process
(`run`, `site`, `site-batch`, `channel`), the Watch sub-apps (`watch_app`,
`topic_watch_app`) plus `catch-up`, the Library leftovers (`add`, `remove`,
`diff`, `trends`), and the `topic_app` / `intent_app` / `concepts_app` sub-apps.
They share ~10 helpers used across group boundaries — `_preflight`,
`_invoke_command`, `_resolve_intent`, `_validate_learning_options`,
`_run_learning_command`, `_preview_learning_selection`, `_load_topic_profile`,
`_process_video`, `_process_site_seed`, and the topic-watch ranking helpers — and
`catch-up` / `topic-watch run` *call* the batch commands (`papers`, `paper`,
`site_cmd`, `site_batch_cmd`). That call-graph is the reason a naive "move Watch
first" churns: `watch.py` would import a dozen commands back from `_logic` that
then move themselves.

**The sequencing that avoids churn:**

1. **Shared helpers to the foundation first.** Move the cross-group `_*` helpers
   into `commands/_helpers.py` (already the no-upward-imports foundation that
   `get_config` / `_resolve_topic_for_channel` live in). Once a helper is in the
   foundation, every later command module imports it from one stable place
   instead of back from `_logic`. Helpers used by a *single* surviving group stay
   with that group. This is the load-bearing step — it turns the remaining moves
   from "import a moving target back" into "import a settled foundation symbol."
2. **Discover + Process commands** into `commands/discover.py` and
   `commands/process.py` (or one `commands/pipeline.py` if the shared-helper set
   is small enough after step 1). These own the batch commands the Watch group
   calls.
3. **Watch last**, into `commands/watch.py` — now its calls to `papers` /
   `site_batch_cmd` resolve to *settled* modules (lazy-imported at the call site
   where a cycle would otherwise form, the same pattern `topic_show` and the
   report/export callers already use). The sub-app mechanics: the
   `watch_app = typer.Typer(...)` / `topic_watch_app = typer.Typer(...)`
   construction and their `app.add_typer(...)` wiring move into `watch.register()`
   (mirroring how `view.register()` attaches its commands). `cli.py` currently
   re-exports `watch_app` / `topic_watch_app` from `_cli_impl` with no external
   users — drop those re-exports or point them at `commands/watch.py`.
4. **Library leftovers + the `topic_app` / `intent_app` / `concepts_app`
   sub-apps** fold in alongside, by the same sub-app pattern.

**The stale-patch hazard is sharper here** because these commands are the
most-tested. The same rule applies — repoint every `monkeypatch.setattr(_cli_impl,
…)` / `patch("distill.commands._logic.…")` in the *same* PR and run the grep gate
— and the multi-module `mock_config` fixture in `tests/unit/commands/
test_cli_wiring.py` keeps growing one `_<module>.get_config` line per extracted
group (the established shape). A bug-hunt pass (2026-06, three review agents)
already found and fixed eight *false-pass* stale patches that the green suite
could not see — tests that patched a moved command's old namespace and passed
while testing nothing — so the per-PR grep gate plus a periodic false-pass sweep
are both part of the contract for Phase 2.

The endpoint is unchanged: `_logic.py` shrinks below the 1000-line cap, then
disappears as a named module, and the ratchet allowlist empties. `cli.py` becomes
the wiring-only entry point the [target layout](../../ROADMAP.md#target-package-layout-10)
describes.
