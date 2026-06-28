# Verification depth: contracts, mutation testing, fault injection

Status: planned (1.0 quality bar). This is the implementation plan for the
"Verification depth (where it matters, not everywhere)" item in
[`ROADMAP.md`](../../ROADMAP.md#100--stability-commitment--quality-bar).

## What's next, and why this and not something else

The 1.0 quality bar has five strands: the Pyright-strict ratchet, parse-don't-
validate, branch coverage 89 -> 95, verification depth on the deterministic core,
and the presentation pass. The recommendation is to make **verification depth the
next focused milestone**, ahead of grinding the strict hard tail or chasing raw
coverage. Five reasons:

1. **The timing is ideal and will not come again cheaply.** The deterministic
   core - `concepts/` (merge, normalize, recovery), `library/` (slugs,
   frontmatter, links), and `pipeline/` (verify, dedup, evidence intervals) - is
   now fully `# pyright: strict`. Types prove *shape*; contracts and mutation
   testing prove *behavior*. Layering behavioral proofs on a freshly type-clean
   core compounds: `deal` generates Hypothesis tests from the contracts, which
   stack with the already-shipped `tests/unit/concepts/test_playbook_stateful.py`
   state machine. The roadmap deliberately sequences these *after* the strict
   pass on the same layer, and that pass is done for the core.

2. **It is the product thesis, made executable.** Distillr's whole value is a
   *verifiable* corpus. The deepest expression of that is proving the
   verify/merge/dedup core is correct under adversarial conditions, not just
   asserting it in prose. The competitive analysis named "trust is the new
   quality frontier"; this is that frontier turned inward on our own core.

3. **Mutation testing is diagnostic for the coverage milestone.** Branch
   coverage answers "did a test execute this line?"; it does not answer "would a
   test *catch* a regression here?". Mutation testing answers the second
   question. Running it first tells us whether the 3,140+ tests are *effective*
   or merely *present*, and it reprioritizes the 89 -> 95 push toward efficacy
   rather than chasing percentage on presentation-heavy code. Doing
   verification-depth before the coverage grind makes the coverage work smarter.

4. **It is greenfield and bounded, not grind.** The strict ratchet's remaining
   work is the coordinated `mcp/` helper promotions and the large `pipeline/`
   modules - real work, but diminishing per-cycle value, better as background.
   Verification depth is new, high-signal infrastructure scoped to a
   well-understood core.

5. **It is a named 1.0 gate that is currently almost untouched** - only the
   stateful property suite exists.

What this is explicitly **not**: blanket contracts or mutation testing across
14k+ lines. Verification depth is scoped to the pure-Python deterministic core
and the external-service boundaries, because that is where correctness is
load-bearing and where the cost/value trade-off actually lands. Presentation
code (CLI rendering, web routes) is out of scope.

## Tooling (researched 2026-06, spend $0.00)

- **`deal`** for Design by Contract. Integrates with pytest, flake8/ruff, sphinx,
  and Hypothesis; generates property tests directly from contracts; production-
  used since 2018. Contracts run in dev and CI and are optimized out with
  `python -O` where overhead matters. (Alternative considered:
  `icontract` + `icontract-hypothesis` - equally mature; `deal` is chosen for its
  tighter Hypothesis test generation and the roadmap already names it.)
  Sources: [deal](https://github.com/life4/deal),
  [icontract](https://github.com/Parquery/icontract).
- **`mutmut`** for mutation testing. AST-based, fast (~1,200 mutants/min in
  third-party benchmarks), the most actively maintained Python mutation tool, low
  memory, ~5 min CI overhead. Uses `# pragma: no mutate` to whitelist. (Alternative
  considered: `cosmic-ray` - stronger build-tool/CI integration via TOML config
  but slower and a heavier setup; `mutmut` wins on speed and maintenance for our
  scoped use.) Sources:
  [mutation-testing comparison (NSF)](https://par.nsf.gov/servlets/purl/10573281),
  [cosmic-ray](https://github.com/sixty-north/cosmic-ray).
  **Platform note (found while spiking, 2026-06-26):** `mutmut` 3.6 has no native
  Windows support (it relies on `fork()`/`setproctitle`) - on Windows it requires
  WSL. Development here is on Windows, but the mutation pass is a CI *cadence* job
  and CI runs on `ubuntu-latest` (the same runner as the coverage matrix), so this
  is not a blocker: install `mutmut` *in that job* (or via `uvx`/`uv run --with`),
  not in the always-synced dev group (it also drags in `textual`/`setproctitle`/
  `mdit-py-plugins` that the rest of dev does not need). If a *local* Windows
  spike is ever needed, `cosmic-ray` is the Windows-capable fallback; the
  `deal` contracts (Phase 1) run fine on Windows and cover local efficacy in the
  meantime.
- **`CrossHair`** (stretch) for symbolic verification of a few critical pure
  functions (evidence-interval arithmetic). It checks `icontract`/`deal`-style
  contracts via SMT, blurring testing and types - proof-grade for small, pure
  functions, too slow for blanket use.
  Source: [CrossHair](https://github.com/pschanely/CrossHair).

Neither tool runs on every PR. Mutation testing is a *cadence* job (it is too
slow for the per-PR gate); contracts run inline but are cheap and `-O`-removable.

## Plan (phased, each phase a shippable unit)

**Phase 0 - mutation spike (1 cycle, diagnostic).** Run `mutmut` scoped to one
critical, well-tested, pure module - `concepts/merge.py` (154 lines, 344-line
test suite) - against its own unit suite, and record the mutation score
(surviving / total) plus a triage list of the most dangerous survivors. This is
the cheapest possible signal of real test efficacy on the core and calibrates the
rest of the plan. Because `mutmut` cannot run on the Windows dev box (see the
platform note above), the spike runs as a **manually-triggered GitHub Actions
workflow on `ubuntu-latest`** (`workflow_dispatch`), installing `mutmut` ad hoc
(`uv run --with mutmut ...`) and printing the score in the job log - it is not a
gate and not part of the per-PR matrix. Deliverable: the workflow plus the first
recorded score and triage.

Status (2026-06-27): the manual workflow exists at
`.github/workflows/mutation.yml`, with the exact scoped surface configured in
`[tool.mutmut]` (`distill/concepts/merge.py` against
`tests/unit/concepts/test_merge.py`). The first score and survivor triage remain
pending the first Ubuntu dispatch. A local WSL run is not currently available in
this workspace: one registered distro cannot attach its disk, and the other has
only Python 3.8 and no `uv`.

### Phase 1 conventions (settled while landing the first contracts)

Two things were learned wiring `deal` into the strict core; both are now the
house pattern:

- **`deal` is a runtime dependency, not dev-only.** Contracts are written inline
  (`import deal` at module scope), so the package must import on a production
  install. `deal` is pure-Python and light; contracts run in production by
  default and are disabled via `deal.disable()` (the `python -O` "optimize out"
  path) only where overhead is ever measured to matter. The merge runs at
  topic scale (tens to low hundreds of concepts), so the per-call check cost is
  negligible and contracts stay on.
- **Validators are named, typed functions, not lambdas - one ignore per
  decorator.** `deal`'s stubs type the validator parameter as `Unknown`, which a
  bare lambda would leak into a `# pyright: strict` module. A `@deal.post`
  validator receives the *result* (`def v(result: T) -> bool`); a `@deal.ensure`
  validator receives the decorated function's *own signature plus* `result`
  (`def v(arg1, arg2, *, kw, result: T) -> bool`) - so both stay fully typed, and
  the only suppression needed is one
  `# pyright: ignore[reportUnknownMemberType]` on each `@deal.post` / `@deal.ensure`
  line for deal's own stub. (Worked example: `concepts/merge.py`
  `build_merged_concept`.)

**Phase 1 - contracts on the pure core.** Add `deal`. Encode the documented
invariants as executable pre/post/class-invariants on the merge/normalize/
recovery layer:
- merge is idempotent and order-independent;
- a rollback's rebuilt rollup row round-trips the restored frontmatter;
- evidence (credal) intervals never invert (lower <= upper, both in [0, 1]);
- a slug is always a single safe path component; frontmatter round-trips.
`deal` generates Hypothesis tests from these, compounding with the stateful
suite. Contracts are `-O`-removable where overhead matters. Deliverable: the
contract decorators plus their generated-test wiring, green in CI.

Status (2026-06-27): executable contracts now cover the merge interval/source
preservation invariants, path component confinement, the normalize layer's
grouping and threshold guarantees, and recovery's frontmatter-to-rollup row
shape. The remaining Phase 1 target is generated-test wiring from the
contracts.

**Phase 2 - mutmut across the core, on a cadence.** Expand the mutation run to
`concepts/`, `library/`, and `pipeline/verify*` + `dedup.py`, wired as a
scheduled (not per-PR) CI job. Triage surviving mutants and add the specific
tests they reveal. Track the mutation score as a reported metric, not a hard
gate (per the no-brittle-junk charter - a score floor would be a deterministic
gate on a quality proxy). Deliverable: the cadence workflow plus the first round
of efficacy-driven tests.

**Phase 3 - fault injection at the external boundaries.** Deterministic tests
that inject malformed LLM JSON, truncated/empty transcripts, network timeouts,
and yt-dlp failures, asserting the pipeline degrades cleanly (resume-friendly, no
half-written artifacts) and that the no-silent-error-swallowing rule holds under
turbulence - verified, not assumed. The security/robustness round already added
several of these guards (bounded reads, malformed-input degradation, the MCP
no-silent-swallow fix); Phase 3 makes the boundary discipline systematic.
Because the concurrency is asyncio IO, the discipline that matters is async
safety (no blocking calls in async paths, correct cancellation), not shared-
memory thread safety.

**Phase 4 - CrossHair on the arithmetic core (stretch).** Symbolically verify
the evidence-interval arithmetic and the merge-idempotence pure functions for
proof-grade assurance on the few functions where a single off-by-epsilon is
corpus-poisoning.

## Interaction with the other 1.0 strands

- **Coverage 89 -> 95** runs *after* Phase 0/2 inform where coverage is
  load-bearing vs cosmetic. Mutation score, not line percentage, drives which
  branches get tests first.
- **The strict ratchet** continues as background grind (the `mcp/` promotion
  cycle, the large `pipeline/` modules); it does not block verification depth,
  and the core being strict is the precondition this milestone just cashed in.
- **Parse-don't-validate** is folded into the strict ratchet and the boundary
  work; Phase 3's fault injection is its adversarial proof.
