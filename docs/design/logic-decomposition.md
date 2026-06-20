# Decomposing `_logic.py` (design / Frame)

> Status: complete. `_logic.py` was reduced from 9,373 lines to zero and
> deleted, with command ownership moved to focused modules. Remediation #1 from
> [`how-we-build.md`](how-we-build.md). This is the architectural-change case the
> operating model says gets a design doc before code. It executes as many small
> green PRs across sessions, not one big bang. Live status is in the
> [Phase 2 section](#phase-2-the-coupled-core-status--plan) below.

## Problem & North-Star tie

`distill/commands/_logic.py` began at **9,373 lines / 155 functions** — 9× the
1000-line ceiling, 21× the next file, and a direct violation of the ROADMAP's "one
command group per file" target (now deleted; see Phase 2). It
earns the *feature spine* (not just a harden pass)
because **agent-context-fit is legibility for the dominant reader**: a 9k-line
module can't be loaded or reasoned about in an agent's context window, and it's
the single worst offender. Goal: every command group in its own
`distill/commands/<group>.py`, `_logic.py` disappears as a named module, and the
size-ratchet allowlist stays empty.

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
wrappers over `_logic`. During the migration, each old monolith group moved into
that shape:

1. **Move** the command function(s) + their *group-private* helpers into
   `distill/commands/<group>.py`. Shared helpers moved to `_helpers.py` or a
   focused support owner and were imported back by commands.
2. **Facade:** during migration, `_logic.py` re-exported the moved names
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
(`distill/_app.py`). The size ratchet's allowlist tracked every step down.

**Phase 2 is complete.** Since the Phase 1 boundary the following left the
monolith, each as a green, pure-relocation slice with the ratchet lowered to
match:

- **Discover / Process / Papers** → `commands/discover.py`, `commands/process.py`,
  `commands/papers.py`, with the learning family split into `commands/learn.py`
  to keep both under the cap.
- **Watch** (the `watch` sub-app + `catch-up`) → `commands/watch.py`.
- **View leftovers** (`diff`, `trends`, `add`, `remove`) → `commands/view.py`.
- **Intent / Concepts** sub-apps → `commands/intent.py`, `commands/concepts.py`.
- **Home screen + HTML dashboard renderers** → `commands/dashboard.py`, with
  the root callback now in `commands/root.py` and still importing the dashboard
  lazily to avoid the cycle.
- **Foundation moves** that settle the shared seam so later moves import a stable
  symbol instead of a moving target: `_preflight` / `_invoke_command` /
  `_resolve_intent` / `_detect_ramp_source` / `_apply_verify_override` /
  `_persist_lens` / the shell-completion helpers → `commands/_helpers.py`; the learning
  flow, query expansion, source-rigor filter, and video selection helper →
  `commands/_learning.py` + `commands/_learning_flow.py` (the
  `_validate_learning_options` wrapper was eliminated, consumers point at
  `_learning_flow` directly); the topic-change helpers → `commands/_topic_changes.py`;
  the topic-watch naming/ranking helpers → `commands/_topic_watch.py`.
- **Topic** (`topic_app` plus profile/workflow/summary/bundle helpers) ->
  `commands/topic.py`; `reports.py` imports the bundle helpers from the new owner.
- **Watch-owned display helpers** (`_show_latest_insights` and
  `_print_goal_refreshes`) -> `commands/watch.py`; `cli.py` re-exports
  `_format_date` from `cli_shared` for legacy test compatibility.
- **Site-ingest helpers** (`process_site_seed`, content hashing, and section
  change summaries) -> `commands/_site_ingest.py`; CLI, MCP, discover, and tests
  now patch the new owner.
- **Paper artifact writing** (`write_paper_artifacts`) ->
  `commands/_paper_artifacts.py`; CLI, MCP, discover, and verify tests now
  patch the new owner.
- **Post-ingest concept playbook hook** (`run_concepts_after_ingest`) ->
  `commands/_concept_ingest.py`; paper, learn, discover, and tests now patch
  the new owner.
- **Installed version lookup** (`get_version`) -> `distill._version`;
  dashboard, doctor, maintain, and tests now import from the canonical owner.
- **Channel-list display truncation** (`_truncate_channel_list`) ->
  `commands/_helpers.py`; dashboard tests now call the canonical owner.
- **Shared video helpers** (`_ensure_channel_context`, `_process_video`,
  `_run_scope_report`) -> `commands/_helpers.py`; process, watch, discover,
  and learning tests now call or patch the canonical owner.
- **Learning query expansion and video selection** (`_expand_learning_queries`,
  `_expand_paper_queries`, `_select_learning_videos`) ->
  `commands/_learning.py`; learning and CLI wiring tests now call or patch the
  canonical owner.
- **Learning-flow injection wrappers** (`_preview_learning_selection`,
  `_run_learning_command`, `_process_learning_selection`,
  `_generate_and_export_topic_brief`) -> `commands/_learning.py`; learn,
  discover, topic, and topic-watch now import the canonical owner.
- **Discover helper body** (`_discover_generate_queries`,
  `_discover_fetch_videos`, `_discover_rerank`, `_display_ranked_discover`,
  sizing flow, confirmation, and mixed-source ingest bridges) ->
  `commands/_discover_flow.py`, re-exported through `commands/discover.py`
  for command-level monkeypatches; ingest isolation tests patch the support
  owner.
- **Root callback and final direct command imports** -> `commands/root.py`,
  `commands/concepts.py`, and existing command owners. The bare `distill`
  callback, version flag, global output/cost mode handling, and home-screen
  banner now live in `commands/root.py`; the `concepts` Typer app now lives in
  `commands/concepts.py`; `ask`, `audit`, `claude-md`, `ingest`, `eval`,
  `process`, and `view` import their canonical helper owners directly instead
  of reaching through `_logic`.

`_logic.py` is down from **9,373 -> 0 lines** and is deleted. Thirteen dead
scaffold modules were deleted along the way, the remaining dead scaffold
comments in `_logic.py` were removed with the paper artifact move, no production
command module imports `_logic`, and the private compatibility bridge surface
now lives directly in `distill._cli_impl`.

**Remaining compatibility surface:**

- `distill._cli_impl` still exports private names used by `distill.cli` and
  legacy tests, including `app`, `main`, `get_config`, `_default`,
  `_resolve_video_channel_name`, topic-change bridge exports,
  learning/discover aliases, `concepts_app`, and other private compatibility
  re-exports.

**A noted follow-up (behavior-touching, separate from the pure moves):** the
dashboard slice was a pure relocation, so `_show_dashboard` still collects its
data inline rather than consuming the shared `dashboard_snapshot()` that
`_render_dashboard_html` already renders from. Consolidating it onto the shared
snapshot would dissolve ~20 collector dependencies but changes the rendered
warnings set, so it is a deliberate refactor with its own test, not a move slice.

**The stale-patch hazard is sharper here** because these commands are the
most-tested. The rule is to repoint every stale `monkeypatch.setattr` or
`patch(...)` in the same PR, run the grep gate, and keep the multi-module
`mock_config` fixture in `tests/unit/commands/test_cli_wiring.py` growing one
`_<module>.get_config` line per extracted group (the established shape). The
topic-watch extraction added
`topic_watch.get_config` to that fixture and repointed its `_run_learning_command`
and `_preview_learning_selection` monkeypatches to the new module. The topic
extraction added `topic.get_config` and repointed the topic videos-only
`_run_learning_command` monkeypatch to `commands.topic`. A bug-hunt pass
(2026-06, three review agents)
already found and fixed eight *false-pass* stale patches that the green suite
could not see — tests that patched a moved command's old namespace and passed
while testing nothing — and the dashboard slice's fixtures were verified
load-bearing (the home-screen tests pass *because* `dashboard.get_config` is
patched, not by accident). The per-PR grep gate plus a periodic false-pass sweep
are both part of the contract for Phase 2.

The endpoint is reached: `_logic.py` is gone and the ratchet allowlist is empty.
`cli.py` remains the wiring-only entry point the
[target layout](../../ROADMAP.md#target-package-layout-10) describes.
