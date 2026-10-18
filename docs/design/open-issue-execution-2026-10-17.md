# Open issue execution plan, October 17, 2026

Status: implementation, second bug hunt and local release gate complete;
exact-commit hosted CI and publication pending.
Reviewed base: `b5a75036a7cac70523b7566a0113b69485ec7ab3`, published 0.20.6.

## Outcome and authority

Resolve all 18 open issues, #40 through #57, in dependency order. The operator
requested implementation, another bug hunt, local zero-dollar validation,
one clean main branch with passing CI, and an updated release. No metered model
calls are authorized. Each issue closes on demonstrated behavior or a documented
resolution of an explicitly offered alternative, never on a plan alone.

The next release is 0.20.7. Its scope is expanded here before implementation
to include the requested trust, provider, toolchain, and interface repairs.
The existing active-generation and derived-origin obligations remain required.
The 0.20.8 semantic evaluation baseline, 0.20.9 broader platform evidence, and
0.20.10 freeze-time security obligations remain distinct from this maintenance
release. Local validation cannot replace those remaining release gates.

## Why this order

Discovery failure, hidden revisions, and unknown freshness can falsely certify
currency. Verification coverage and citation origin can falsely certify support.
Correct those claims before tuning presentation or collecting polished journey
receipts. Revised-source publication must wait for successful generation
replacement, including zero-claim retirement and failure preservation.

| Step | Issues | Outcome and implementation boundary | Required evidence |
|---|---|---|---|
| 1 | #51 | Preserve explicit versus filesystem timestamps; normalize to UTC; propagate current, stale, and unknown through existing freshness consumers | Newer explicit input within one hour is stale; equivalent offsets agree; missing/unreadable scoped inputs are unknown; modality isolation and legacy support |
| 2 | #49, #44 discovery hint | Typed per-query coverage through existing arXiv search, preview, summaries, and persisted shortlist; API errors and invalid feeds are failures | Official Atom error fixture; malformed versus empty; partial/all-failed searches; replay retains coverage; pacing and budgets unchanged |
| 3 | #50 preview | Separate work and revision identity; expose newer or ambiguous revisions without automatic publication | Same revision no-op; v1 to v2 visible; no downgrade; unversioned uncertainty; replay stays pinned to reviewed v2 after v3 appears |
| 4 | #43 and existing 0.20.7 trust scope | Keep retrieval artifact identity and derived origin; exclude operational outputs; replace successful active generations atomically while retaining history | Unsupported insight cannot borrow a source citation; audit/answers excluded; complete/partial/invalid/zero-claim extraction; legacy reads; synthesis has no stale fallback; concept-generation review |
| 5 | #42, #45 | State numeric versus semantic coverage; strict refusal reaches exit code and summary; consistent ingest verify option | Numeric-only never reads as fully verified; absent/failed semantic checker visible; strict refusal nonzero without artifact publication; accurate counts and CLI contract |
| 6 | #46 | CPU installation recipe and measured optional-extra behavior; inspect pinned HHEM tokenization before altering context handling | No CUDA requirement in CPU recipe; explain known warning; evidence beyond token 512 remains available; failures stay visible; no global warning suppression |
| 7 | #41 | Current curated Gemini models and lifecycle checks; direct stable default; conservative future billing ceilings; historical ledgers remain readable | Primary-source dated model/pricing audit; alias and retirement behavior; current/future rate tests; no paid calls or uncalibrated route expansion |
| 8 | #48 | Update pinned Actions and promote newest stable Python only where the locked core stack passes; decide the explicitly offered Python-floor alternative with evidence | Full core matrix and wheel smoke; optional entailment availability explicit; SHA verification; preserve filesystem junction defenses; no silent skipped extra |
| 9 | #40, #44 remaining, #52, #53, #54, #55 | Quiet terminal, copyable paths and commands, intent-based help, consistent route-aware diagnostics | 60/80/120 columns; pipe/dumb/NO_COLOR; -h on all apps; no routine motion or screen clear; no false paid-route requirement; JSON routing and contract checks |
| 10 | #56 | Shared strict theme tokens for server/export, Dark/Light/System, accessible starter palettes, safe theme lifecycle, copy controls | Contrast contract on every theme; untrusted file/URL/path tests; persisted appearance; reduced motion; web/export parity; browser accessibility and layout evidence |
| 11 | #47, #57 | Numbered honest README, local journeys, no-op/recovery receipts, interface tracker reconciled | Wheel/hash/platform/model/cost/exit/artifact receipts; unchanged versus explicit rerun; lock safety explained and tested; all child issues demonstrated |
| 12 | all | Independent second bug hunt, regression fixes, final gate, one main branch and release | Frozen lock/sync, lint/format, Pyright warnings denied, import contracts, >=95% branch coverage, security, contracts/distributions/build, installed wheel, exact-commit CI and publication receipts |

Each step updates this record with commands, results, changed contracts, and
limitations. Closely related changes may share a commit; issue acceptance stays
individually reviewable. GitHub issue updates happen after concrete fixes exist.

## Findings that change the proposed fixes

- HHEM-2.1-Open is documented as accepting unlimited context; the earlier HHEM
  version has the 512-token limit. A tokenizer warning does not prove truncation.
  Inspect the pinned implementation and prove tail evidence survives before
  imposing arbitrary 512-token windows.
- Advisory lock files must retain a stable identity while other processes may
  hold or await them. Removing them after each command can split mutual exclusion.
  Treat persistent lock files as coordination state, not abandoned artifacts;
  any relocation requires cross-version concurrency evidence.
- Python's maintained versions do not automatically define this package's floor.
  #48 explicitly permits retaining 3.12 with a recorded reason. Evaluate the
  benefit of 3.11 support against rewriting established syntax and confinement
  primitives; do not weaken junction protection to change a classifier.
- Retired model IDs must be rejected for new execution as appropriate, while
  historical receipts and pricing remain interpretable. Do not delete evidence
  or break old ledgers to simplify a menu.
- #56 includes a theme import/update subsystem, not just two palettes. Validate
  it at existing URL, child-process, and filesystem boundaries. Theme data never
  executes code, imports CSS, or supplies template markup.
- Hiding commands or changing exit codes affects covered interfaces. Preserve
  discoverability and document intentional contract changes with snapshots.

## Primary sources checked

- [arXiv API manual](https://info.arxiv.org/help/api/user-manual.html): Atom
  error entries, explicit revisions, publication/update dates, request spacing.
- [Gemini models](https://ai.google.dev/gemini-api/docs/models),
  [deprecations](https://ai.google.dev/gemini-api/docs/deprecations), and
  [pricing](https://ai.google.dev/gemini-api/docs/pricing): the 3.7 Flash alias,
  3.8 Flash, Argon, and scheduled price increases.
- [Python supported versions](https://devguide.python.org/versions/): Python
  3.15 is stable; dependency readiness remains a separate requirement.
- [PyTorch installation](https://pytorch.org/get-started/locally/): explicit
  CPU installation and current optional runtime support limits.
- [HHEM model card](https://huggingface.co/vectara/hallucination_evaluation_model):
  HHEM-2.1 context behavior differs from HHEM-1.0.
- [checkout releases](https://github.com/actions/checkout/releases/latest) and
  [setup-uv releases](https://github.com/astral-sh/setup-uv/releases/latest):
  current stable releases must be resolved to immutable commits before use.
- [WCAG contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
  and [Click help](https://click.palletsprojects.com/en/stable/documentation/):
  contrast checks and documented help customization.

## Evidence ledger

- Fetched and fast-forwarded main by three commits to the reviewed base.
- GitHub CI passed on that exact base; no open pull requests; 18 open issues.
- Frozen lock/sync, format, Pyright (zero diagnostics), all four import contracts,
  public contracts, canonical distribution checks, Bandit and dependency audit
  have passed locally during implementation. The final stable-tree gate remains
  required; historical or intermediate results do not certify it.
- Implemented all issue groups through the canonical paths above. Added failure,
  history, revision, origin, timing, terminal and theme regression tests.
- The second bug hunt found grouped citations refusing a valid local answer,
  answer refusal returning exit zero, hidden local history entering source
  discovery, changed-during-call evidence publication, failed unchanged claim
  refresh appearing complete, newline translation corrupting receipt hashes,
  reuse ignoring a changed prose threshold, and optional checker failures losing
  their status. Installed failure journeys additionally found site seed rejection
  and paper publication refusal returning success. The shared paper writer now
  propagates refusal to CLI/MCP items, and all-failed batches stop before synthesis.
  Repairs and regression coverage precede final validation.
- A real CPU-only local model journey completed setup, bench, current arXiv
  preview, interrupted-ingest recovery, no-op, force rerun, audit and pinned
  paper replay at $0. The earlier answer refusal is retained as a failed
  candidate receipt, not relabeled as a passing journey.
- A real CPU HHEM probe retained evidence after token 512. Browser checks
  reported zero automated WCAG A/AA violations across four pages in both house
  themes and export, with mobile layout, keyboard, copy, System mode and theme
  lifecycle interactions exercised.
- The locked Python 3.15 Linux container builds and passes version/theme/uvloop
  smoke checks. Fresh-install failures exposed targeted wheel compatibility
  updates rather than changes to provider SDK behavior.
- Six retained native plugin evaluation cases and their reports remain
  hash-matched. Canonical skills, references, evals and bundled runtime skill
  content are unchanged since v0.20.1; distribution version metadata is regenerated.
- Sanitized intermediate evidence is in
  [the receipt directory](../research/evidence/2026-10-17/), with SHA-256 sums.
  The final local gate passed 7,672 tests with 95.40% combined coverage and
  branch measurement enabled. Lint/format, zero-diagnostic Pyright, imports,
  security/dependency audits, contracts, archives, installed wheel and locked
  Linux container checks passed. Exact-commit hosted CI and publication remain
  separately required.
- No cloud inference or metered API call has been made. Local on-device
  inference is recorded separately from deterministic offline tests.
- The first pull-request CI passed all six platform/runtime test jobs but found
  a wheel-resource failure: uv hardlinks trusted packaged palettes. A focused
  regression and an installed Linux hardlink smoke now cover that boundary;
  mutable user palettes retain their stricter confinement.
- Follow-up optional dependency review raised patched torch, fsspec and
  setuptools floors, pinned nested HHEM metadata, and proved actual CPU scoring
  on Windows Python 3.15. Remaining Transformers version alerts retain their
  [path-specific assessment](../research/optional-dependency-review-2026-10-17.md)
  rather than a blanket dismissal.
- The frozen follow-up tree passed 7,680 offline tests with 95.40% combined
  coverage and branch measurement enabled. Full Pyright reported zero
  diagnostics. The refreshed container passed real Chromium rendering, and the
  installed CPU verification probes exercised warn and strict publication.
