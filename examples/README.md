# Example corpus

`library/topics/claim-verification/` is **real distill output**, unedited: the
corpus distill built about its own next milestone (the 0.10 write-time
claim-verification hook) on 2026-06-11, via

```bash
distill discover "Design a write-time claim verification hook for an LLM research pipeline: \
grounding extracted claims (numbers, named entities, dates) against source documents, \
claim decomposition, small local entailment checkers and hallucination detection models, \
citation faithfulness evaluation" --topic claim-verification --paper-limit 6 --preview
distill discover --from-preview 476d577294 --topic claim-verification --yes
```

Six arXiv papers, ingested and analyzed for **$0.19** in 2m38s on the
`grok-4.3` default. What you're looking at:

- `papers/<paper>/<slug>_Insights.md` — per-paper structured analysis (claims,
  methods, limits, open questions) with full YAML provenance (`source_id`,
  `url`, `analyzed_by`, `prompt_id`).
- `claim_verification_Paper_Synthesis.md` — the cross-paper synthesis:
  claims no single paper makes, a comparison matrix, shared blind spots, and a
  falsifiable thesis with named white space.
- `CLAUDE.md` / `AGENTS.md` — the auto-generated orientation files coding
  agents pick up when they enter the directory.
- `intent.json` — the persisted goal/lens that shaped the analysis.

**Content policy (the rule, not an exception):** example corpora in this repo
**never include captured source content** — no paper full texts, no video
transcripts, no scraped page bodies. Other people's work doesn't get
redistributed here. What ships is distill's own analytical writing
(insights, synthesis) plus bibliographic metadata and the `url` receipts to
fetch every source yourself; a real run keeps the captured artifacts
(`<slug>_Paper.md`, `<slug>_Transcript.txt`, `<slug>_Content.md`) on **your**
disk next to the analysis, which is exactly where they belong.

This corpus is also a working input: its findings (adapted small-NLI checkers
approach GPT-4o on grounding; claim decomposition is non-optional; numerical
claims are the hard class) are cited in the verify-hook design in
[`ROADMAP.md`](../ROADMAP.md#0100--verified-corpus-run-time-verify--self-maintaining-audit).
