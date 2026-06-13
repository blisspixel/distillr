# The entailment tier: prose claims and named entities, checked locally

Status: design accepted 2026-06-12; implementation targets 0.13.0.
Companion to the shipped deterministic tier (`distill/pipeline/verify.py`,
0.10.1) -- this tier layers on top of it and never replaces it.

## Why this exists

The deterministic tier checks numbers, percents, money, and years by pure
string/arithmetic matching. Its limitation classes are named in its module
docstring so nobody over-trusts it: derived arithmetic flags as unsupported,
support is presence not context, bare small integers are unchecked, and
**prose claims carry no checkable tokens at all**. The entailment tier exists
to close exactly these -- "RoMem outperforms ChronoR on every benchmark" can
be wrong while containing no number the deterministic tier can see.

The corpus settled the design before this doc was written. The
claim-verification topic (6 papers, $0.19, ingested 2026-06-11) was built to
answer this question, and its promoted `distill ask` answer -- the corpus's
first derived insight -- concluded:

- **HHEM-2.1-Open** (Vectara, ~110M params, Apache 2.0) as the default
  checker: CPU-feasible, trained specifically for factual-consistency
  scoring of (evidence, claim) pairs, free.
- **IBM Granite Guardian via Ollama** as the higher-accuracy local option
  for boxes already running Ollama.
- **Auto-GDA-style synthetic domain adaptation** as the upgrade path: a
  domain-adapted small NLI verifier approaches GPT-4o on grounding
  (DeBERTa 0.708 -> 0.878 ROC-AUC vs GPT-4o's 0.883).
- **Claim decomposition measurably helps** (subquestion decomposition:
  59.6 vs 36.9 F1 on PolitiFact) -- so the claim unit is the sentence/bullet,
  never the paragraph.
- Avoid NC-licensed checkers (Bespoke-MiniCheck).

Per the invariants: **LLM proposes, Python decides.** A 110M cross-encoder
emitting a calibrated score that a threshold turns into a flag is a
*classifier*, not an LLM-as-judge-of-record; the analysis model's biases are
not shared by the checker, which is the point.

## Architecture

New module `distill/pipeline/verify_entailment.py`, isolated from
`verify.py` so the deterministic tier stays dependency-free and pure:

1. **Claim extraction (deterministic).** Sentence/bullet units from the
   insight body -- same frontmatter/fence/URL exclusions as the numeric
   tier. A unit is an entailment claim when it is >= 40 chars of prose.
   Units already fully covered by numeric checking are still scored (a
   correct number in a wrong sentence is the context-blindness class).
2. **Evidence pairing (deterministic).** The source receipt is chunked into
   ~1,500-char windows (HHEM's input budget), each claim is paired with its
   top-K (default 3) chunks by token overlap -- the same cheap lexical
   ranking the corpus already uses elsewhere; no embeddings, per the
   no-database invariant.
3. **Scoring (the model).** `EntailmentChecker` protocol:
   `score(evidence: str, claim: str) -> float` in [0, 1]. Implementations:
   `HHEMChecker` (transformers, lazy import), `OllamaChecker` (Granite via
   the existing Ollama adapter), and the test double. A claim's score is the
   max over its paired chunks; below threshold (default 0.5,
   `DISTILL_ENTAILMENT_THRESHOLD`) it is flagged.
4. **Sidecar (additive).** `_Verify.json` schema_version 2 adds an
   `entailment` block: `{checked, supported, flagged: [{claim, score,
   best_chunk_preview}], model, threshold}`. v1 sidecars stay valid; the
   audit rollup treats a missing block as "entailment not run".
5. **Modes.** The existing `warn | strict | off` applies unchanged; strict
   refuses the write on either tier's flags. When the optional dependency is
   absent, the tier is silently skipped (today's behavior is the fallback,
   never an error) and `distill doctor` shows availability.

## Packaging

Optional extra: `pip install distillr[entailment]` pulls
`transformers` + `torch` (CPU build is sufficient; CUDA accelerates it on a
4090-class box). CI does not install the extra -- unit tests mock the
`EntailmentChecker` protocol; the model-loading path is covered by marked
opt-in integration tests and live validation.

## Verify on synthesis emits (rides along)

The second remaining 0.10 item. Cross-source synthesis is the artifact most
prone to attribution swaps and is not yet checked. Both tiers run at
synthesis write time with the **per-source insights as the receipt** (the
synthesis's inputs are its evidence). Same sidecar (distinct identity, e.g.
`<topic>-paper-synthesis_Verify.json`, so the three topic-level syntheses
don't collide), same modes; strict refuses the synthesis write and keeps the
previous synthesis in place.

Sequencing: 0.13.0 shipped it on the **paper synthesis** path, where the
receipt (the per-paper insights) is already in the function's hands. 0.13.1
completed the set — channel (per-video insights), topic (channel syntheses),
corpus single-pass (per-source sections), corpus two-pass (the rendered claim
set), site (per-page insights), and site-topic (site syntheses) — via a shared
`run_synthesis_verify` helper. A two-pass strict refusal returns `None` (vs
`""` = no claims) so it surfaces instead of falling through to a paid
single-pass write, and `distill audit` counts synthesis sidecars separately
from insight sidecars.

## Validation plan (free)

- Frozen fixtures: hand-labelled supported/unsupported prose claims over the
  claim-verification corpus's own papers, plus QuanTemp-style numeric-prose
  probes for the conflicting-claims hard class.
- Live: pull HHEM-2.1-Open once on the dev box, run the tier over the
  claim-verification and agentic-harness topics, inspect flags by hand.
  Local model, zero spend.
- Calibration: threshold picked on the fixtures, not vibes; the eval harness
  records precision/recall per threshold so the default is a measured choice.

## Out of scope (deliberately)

- Cloud entailment APIs (the tier's reason to exist is local-first).
- Auto-GDA adaptation itself -- the upgrade path is documented, not built;
  it needs a synthetic-data pass that deserves its own slice.
- Cross-document contradiction mining (the contested-concepts surface
  already covers the cross-source case at the concept level).
