# Design invariants

What distill is, what it is not, and the rules that don't bend. This is the charter
contributors and downstream consumers (e.g. [Deepr](https://github.com/blisspixel/deepr))
can build against without expecting churn. Features change; these don't.

## In one line

**Distill helps you get insights from specific things and topics — and keep them current —
by turning sources into a local, plain-Markdown corpus you and your agents can query.**

You point it at things you care about (a paper, a channel, a vendor's docs, a research
goal), it captures and analyzes them into structured insights with provenance, synthesizes
across them, and lets you refresh on a cadence. The corpus is the product; the pipeline is
how it gets fed.

## Why plain Markdown (and why this is now the right shape)

Andrej Karpathy's April-2026 [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
pattern made the case crisply: an agent-maintained folder of Markdown — ingest, query,
lint — *compounds*, and at corpus scale (~hundreds of pages) it works "without embedding
pipelines or vector databases. The cross-references are already there." The maintenance
cost that makes wikis rot for humans is near zero for an LLM. Distill is the rigorous,
reproducible version of that pattern: deterministic source ingestion, structured per-source
insights, cross-source synthesis, provenance on everything — the parts the
point-an-agent-at-a-folder tools leave to improvisation.

## What distill IS

- A **source → intelligence pipeline** (capture → analyze → synthesize) that produces a
  local, plain-Markdown corpus with structured per-source insights and cross-source
  synthesis.
- The **persistent memory layer** agents query — over MCP and over the filesystem — and
  that humans browse in Obsidian/grep. It is the corpus other tools consult, not a chat
  agent itself.
- **Provenance-first and verifiable.** Every artifact carries its source, URL, and the
  `prompt_id` / `model_version` that produced it. You can always trace a claim to a source.
- **Compounding.** Outputs can become inputs — a good answer can be filed back as a
  first-class source — so the corpus gets richer with use, gated by a grounding check.
- **Stay-current by design.** Topics refresh on a cadence; "what changed" is a first-class
  question (`diff`, `trends`, watch-alerts), not a re-run from scratch.

## What distill IS NOT

- **Not a database of record.** No SQLite, Postgres, or vector store holds canonical state.
- **Not a RAG black box.** Knowledge is pre-compiled into structured pages, not retrieved as
  raw chunks per query.
- **Not a proprietary format or viewer.** Plain `.md` + YAML frontmatter, readable by
  Obsidian, grep, and any agent. No lock-in, no bespoke app required.
- **Not a general web crawler.** Ingestion is seed/source-driven and reproducible from
  public inputs — no login walls, captcha defeat, or scraping that breaks on anti-bot.
- **Not a multi-provider prompt zoo.** The model set is deliberately bounded so prompt
  calibration stays tractable.
- **Not an interactive agent.** Distill does long-running batch ingestion and corpus
  maintenance — the things interactive agents are bad at — and exposes the result.

## The hard invariants (each one testable)

1. **Markdown is the source of truth.** The entire corpus is reconstructable from the
   `.md` + `.jsonl` files alone. Delete the `.distill/` ops directory (caches, logs, any
   index) and nothing *of record* is lost.
2. **Any index is derived and disposable.** If an embedding or SQLite index is ever added
   for speed, it lives under `.distill/`, is git-ignored, is rebuildable from the Markdown,
   and is never read as authoritative. The corpus must function fully without it. *(This is
   the precise line on "should we add a DB?" — a derived accelerator: yes, eventually,
   maybe; a record-of-truth: never.)*
3. **Stable identity.** One canonical slug/path per artifact; renames never orphan
   backlinks (`distill doctor --links` enforces it).
4. **Provenance on every artifact.** No insight is written without `source_id` + `url` +
   `prompt_id` + `model_version`.
5. **Deterministic, idempotent merges.** Knowledge-layer rollups (`mentions.jsonl`,
   `claims.jsonl`, concept/entity notes) are pure functions of append-only row logs;
   re-running a merge is order-independent and changes nothing.
6. **LLM proposes, Python decides.** Models emit rows and prose; structural decisions —
   merge, dedup, canonicalization, thresholds, verification — are deterministic code.
7. **No off-ledger spend.** Every model and transcription call is cost-tracked.
8. **Verification gates re-ingestion.** A generated answer becomes corpus only after a
   grounding check against its cited sources.

## What this means for integrations

These invariants are the contract downstream tools build on. In particular, anything that
reads or syncs the corpus — incremental "what changed since X" pulls, grounding a claim
against supporting/contradicting excerpts, belief updates over the claim layer — composes
cleanly *because* it reads Markdown and provenance, not a private store. The moment a
feature would require a database of record to be correct, it's out of scope by invariant 1,
not by opinion.

See [`architecture.md`](architecture.md) for how the pipeline implements these, and
[`../ROADMAP.md`](../ROADMAP.md) for what's planned on top of them.
