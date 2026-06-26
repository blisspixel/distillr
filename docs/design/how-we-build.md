# How we build distillr (DRAFT for thumbs-up)

> Status: **draft**, refined by a five-persona mock-team review (principal eng,
> PM, dual-audience UX, quality/security, pragmatist). Supersedes the separate
> `operating-model.md` + `engineering-standards.md` drafts (merged here on the
> pragmatist's call: two docs re-derived the same North Star, team shape, and
> standards the ROADMAP already owns). Not adopted until the product owner
> thumbs-up the highlights.
>
> **This doc was itself caught violating its own first rule.** The draft asserted
> "Hypothesis is unused" (27 `@given` suites exist) and "SBOM/PEP 740 not yet
> shipped" (both live in `publish.yml`) - both recalled, neither verified. The
> review caught them. That is Exhibit A for §3 and for the review panel, and the
> reason both exist.

## 1. North Star

distillr is a **self-maintaining, always-current research corpus, first-class for
both AI agents and humans.** You point it at topics; it discovers, captures,
verifies, and synthesizes; it stays current on a cadence. Agents are the
*realistic dominant reader* (most Markdown is consumed by an AI via MCP/file
reads/`ask`); humans browse the *same* plain files. As local LLMs improve,
ingestion approaches zero marginal cost - "always up to date for you or your AI."

**The metric** (so "what's next" is falsifiable, not vibes): **% of corpus
load-bearing claims that are verification-clean**, already computed by
`distill audit` (clean / flagged / never-checked). Guardrails: median
source-relative freshness, and autonomous-run success rate (loop runs completing
exit-0, no human touch). A milestone that moves neither owes a written "why" in
its Frame.

**The prioritization rule** (when candidates compete): rank by *how much more
corpus content an agent can consume without a human and without being wrong.*
**Trust > currency > legibility** when they conflict (unverified-but-fresh scales
slop - the ROADMAP's own sequencing of verify before breadth). The dominant
reader (agent) is the tiebreaker.

"Humans" is three segments with different needs: the **maintainer** (runs
ingestion, owns the corpus - the loop-ready/unattended features serve them), the
**consumer** (queries a corpus they didn't build), and the **contributor**.

Non-goals (ROADMAP owns the full list): not a memory layer, not hosted SaaS, not
generic RAG, not a graph-UI.

## 2. Team shape (why this isn't a copy of a 50-person playbook)

One product owner (Nick) + one AI executor (Claude) that forks a review panel on
demand. Consequences: review is cheap and parallel (so review *the right
amount* - §4); design docs are cheap to write but expensive to skip (front-load
the 1-pager); the **scarce resource is the owner's attention**, so the process
optimizes for few high-signal thumbs-up gates, not ceremony.

## 3. The AI-discipline rules (the part a generic charter lacks)

The executor has a knowledge cutoff and no concept of "today." These are the
highest-leverage rules in this doc - and the parts the review said keep verbatim.
Each is framed as an *enforceable gate*, not a creed (a creed an LLM will violate
under pressure; this doc proved it):

1. **Verify, don't recall - and let tools own the enforcement.** For
   time-sensitive facts (versions, APIs, CVEs, "current best practice"), search
   and verify against a current source; never assert from training memory. The
   enforceable backstops already exist: **`pip-audit` owns CVE status**, **the
   `uv` resolver + committed `uv.lock` own versions** (an LLM-typed version can't
   survive `uv sync --frozen`), **Pyright + tests own API signatures**. The only
   residual the tools can't catch is *prose claims* (docs, commit messages,
   charters like this one) → **cite-or-retract, and the reviewer spot-checks
   citations.** ([Anthropic: web search; "reduce hallucinations" - external-
   knowledge restriction]).
2. **Dependencies are verified, never trusted from suggestion.** The gate is the
   **lockfile diff in PR review**, eyeballed by the owner. A Frame that proposes a
   new top-level dep records its PyPI URL, first-release date, and maintainer
   signal (anti-slopsquat: a model re-asked "does this exist?" will re-confirm its
   own hallucination - USENIX found 43% recur deterministically - so the check
   must be external, not the model's belief). Security fixes are never delayed.
3. **Small, reviewable diffs.** Largest agentic-PR rejection driver; smallest
   coherent increment, trunk-green.
4. **Run it before trusting it.** "Looks correct" ≠ "is correct." Behavior
   confirmed by tests/execution, not by reading; the review panel verifies claims
   against the code (it just caught three in this doc).
5. **Resist gold-plating.** No abstraction layers, defensive code, or tests for
   impossible cases. Match the surrounding altitude.
6. **Lean `CLAUDE.md`/`AGENTS.md`, small files.** Each line: "would removing this
   cause a mistake?" Small files/functions so the corpus *and* the code fit an
   agent's context window (the governing constraint).

*Myth-corrections:* "code is a liability" is Brockman, not Anthropic; there is no
primary source for "rewrite agent code every 6 months."

## 4. The cadence

Three core steps a solo+AI flow will actually sustain, plus two conditional:

- **Frame** *(core)* - one paragraph: problem, goals, non-goals, North-Star tie
  (does it move the metric / hold a guardrail?), **and the one failure mode worth
  a test up front** (pre-mortem, folded in - not a separate step that gets
  skipped). → owner thumbs-up before deep work.
- **Design doc** *(conditional - architectural / multi-module only)* - short, in
  `docs/design/`: alternatives, chosen, risks. The `_logic.py` decomposition
  qualifies.
- **Build** *(core)* - small, reversible, trunk-green; full CI gate green on every
  push.
- **Review** *(conditional - gated by blast radius, §below)*.
- **Decision record** *(core)* - CHANGELOG + ROADMAP, including declines; and
  **reconcile as-built vs. the Frame's predicted metric move** (closes the loop).

**Dogfood - opportunistic, not a gate.** When keys + hardware allow, build a
distill corpus on the milestone's domain (high-signal: design evidence + QA +
proof artifact in one sub-dollar run). Skipped without guilt when they don't
(the executor often runs on a secondary box with no keys). N/A for refactor/harden
passes with no domain literature.

**Quality work never blocks features.** It rides the ROADMAP's existing harden-pass
rhythm - *unless* it clears the North-Star test directly, which promotes it into
the feature spine (e.g. `_logic.py` decomposition *is* agent-legibility for the
dominant reader; mutation testing and docstrings are insurance → harden pass).

## 5. The review panel (gated by blast radius)

Default review = **principal engineer + quality/security** (two lenses). The
**full five** (adding PM, dual-audience UX, pragmatist) fire only for
architectural, North-Star-altering, or process changes. A 5-way panel on a
one-group extraction is theater; this very charter is a case where the full panel
earned its keep. Each persona's mandate is to *find problems*, not approve;
verdicts feed the owner's thumbs-up.

## 6. The corpus output standard (the artifact both readers consume)

The code standards (§8) are not enough: the thing both readers actually touch is
the **corpus**. This standard is owned canonically by
[`docs/outputs.md`](../outputs.md) + [`docs/invariants.md`](../invariants.md);
restated here as the dual-audience contract:

- **Frontmatter + provenance complete** on every artifact (`source_id`, `url`,
  `prompt_id`, `model_version`) - invariant #4.
- **Stable slugs, no orphaned backlinks** - `distill doctor --links` green
  (invariant #3).
- **`--json`/MCP parity on every agent-facing read surface** (generalized from
  CLI).
- **Per-topic `CLAUDE.md`/`AGENTS.md` orientation files are first-class output**
  with their own quality bar (a new agent that `cd`s in must get correct
  orientation).
- **Dual-audience tie-breaker** (the question the drafts ducked): single substrate
  is non-negotiable; where readers want different things, optimize the
  **machine-readable layer** (frontmatter, JSON, sidecars, slugs) for the agent and
  the **prose body** for the human - they coexist in one file, so it's additive,
  not a trade-off. We privilege agents only on the *interface* (MCP returns
  paths-not-payloads), never by splitting or degrading the files.
- **Legible at scale, not just per-file:** orientation files + topic syntheses are
  the agent's JIT-retrieval tier. Reviewer test: can an agent answer a topic-level
  question from the index + one synthesis, not N insight files?

## 7. Security invariants (the threat distillr actually has)

Generic hygiene (bandit/coverage/layering) does not catch distillr's real threats:
untrusted ingested content → LLM, and SSRF on fetch. These controls already exist
and are now **named invariants, each backed by a regression/property test; a
bypass is a blocking review failure:**

- **SSRF boundary** - every attacker-influenced fetch goes through
  `distill/ingestors/net.py` (`is_public_web_url` + connect-time IP pinning that
  closes the DNS-rebind window). A new `urllib`/`requests`/`httpx` call to a
  caller-supplied URL that bypasses it fails review.
- **MCP path confinement** - `_resolve_within_library` on every path arg.
- **Output sanitization** - `nh3` allowlist on rendered corpus HTML.
- **Untrusted-content prompt rules** - `UNTRUSTED_CONTENT_RULES` threaded into
  every per-source prompt.
- **Secret handling** - `SecretStr`, never rendered to logs/artifacts.

**Point the rigorous test methods at security first.** Hypothesis (already used on
the deterministic core) extends to the **security predicates**: no private/
loopback/metadata IP escapes `is_public_web_url` across fuzzed hosts/IPv6/redirect
chains/octal-decimal encodings; no traversal escapes the library root; no
`<script>`/`javascript:` survives `nh3`; `SecretStr` never renders. Mutation
testing tiers: **≥80% on the correctness core, ≥90% (→100% on validation
predicates) on the security boundary** - a surviving mutant in the SSRF validator
is a vulnerability, not a cosmetic bug.

## 8. Definition of done

Green CI gate; docs (usage + changelog) updated; decision recorded (incl.
declines). **For corpus-writing changes:** frontmatter/provenance complete,
`doctor --links` green, `distill audit` surfaces no new freshness/duplication
finding. **For agent-facing surfaces:** `--json`/MCP parity *and* readable output,
and first value reachable by both readers (a new human gets a non-empty corpus
from one documented command; a new agent gets correct orientation on `cd`).
**For security-boundary changes:** the §7 invariant's property test covers it.

## 9. Standards: one source of truth

The adopt/adapt/decline standards (uv/lock/frozen, import-linter, pip-audit,
SBOM + PEP 740 *(shipped 0.8.3)*, Pyright-strict ratchet, parse-don't-validate,
branch-coverage ratchet, structlog-not-OTel, declined SLSA-L3/containers/free-
threading/Dependabot) live in **ROADMAP § "Engineering standards: adopted,
adapted, declined"** - not duplicated here. Only what's *new* lives here:

- **Module-size gate** - `≤1000` lines hard. Enforced by a ~15-line
  `test_module_sizes.py` in the green suite carrying a **must-only-decrease**
  allowlist when needed; a PR may lower a number, never
  raise it. (Ruff has no per-file line cap; this is the cheap real mechanism.) A
  `500`-line *informational* warning prompts "is this cohesive?" - **not** a
  defect; the 9 existing cohesive 500-973-line modules are grandfathered.
- **`ruff BLE001` + `E722`** to lock in no-silent-swallowing (housekeeping - audit
  found zero today; the rule keeps it that way).
- **The §7 security property tests.**

## 10. Remediation plan (corrected against the tree, ranked)

**Load-bearing (do):**
1. **Decompose `distill/commands/_logic.py`** (complete; began at 9,373 lines,
   155 functions and is now deleted) - agent-legibility for the dominant reader,
   so it earned the feature spine. **Hazard the drafts missed:** 76
   `from distill.commands._logic import …` sites +
   `monkeypatch`/`patch("distill.commands._logic.…")` strings. Moving a function
   silently false-greened those patches. **Rule:** private compatibility exports
   now live in `distill._cli_impl`; grep `distill.commands._logic` as a
   pre-merge check; sequence move, re-export, repoint patches, then delete facade
   when no live caller remains. Status and
   the per-slice plan: [`logic-decomposition.md`](logic-decomposition.md).
2. **The module-size pytest ratchet** (§9) - the mechanism that makes #1 stick.
3. **Coverage floor as a real ratchet** - store the floor, CI asserts
   `measured ≥ stored`, reject lowering; fix the live **79-vs-80 mismatch** in
   `ci.yml` (comment says 79, command says 80).
4. **Security property tests** (§7) - SSRF/path/sanitizer/secret; highest-value
   new testing.
5. **Rename one `_split_frontmatter`** - `paths.py` and `migration.py` have
   *different* functions sharing a name (different signatures); not a dedupe.
   Rides the decomposition PR.

**Harden-pass / post-1.0 (don't block features, don't gold-plate):** extend
Hypothesis to interval-arithmetic/slug; the `mutmut` periodic pass *with an actual
scheduled trigger* (else "periodic" = "never"); docstring ratchet capped to the
public MCP/CLI surface.

**Dropped (already done / non-issue):** SBOM + PEP 740 (shipped 0.8.3); BLE001 is
housekeeping not a remediation item.

## 11. Revert / yank SLA (for the green-but-wrong release)

Trunk-green doesn't catch the "subtle wrong-but-plausible logic" class (it passes
CI by definition). When a shipped release is wrong in production: **`pip yank` the
bad version on PyPI, ship a corrected patch release, and confirm `distill update`
moves users off it.** A release is not "safe" because CI was green - it's safe once
it's run.

## 12. The 80/20

If everything else is forgotten, these five capture most of the value: (1)
**Frame-with-pre-mortem** gate before deep work; (2) **trunk-green CI**; (3)
**verify-don't-recall + dependencies-verified** (§3.1-3.2 - the only rules that
exist because the author is an LLM); (4) **decompose `_logic.py` + module-size
ratchet**; (5) **decision record** incl. declines. The rest is pointers, harden-
pass work, or won't survive a Tuesday.
