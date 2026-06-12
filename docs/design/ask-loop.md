# `distill ask` -- the output->input loop, verify-gated

Status: design, written at 0.12 slice start per the working rhythm. Spec
skeleton from [`../../ROADMAP.md`](../../ROADMAP.md) (0.12 "Compounding
corpus"); invariant 8 ("verification gates re-ingestion") is the load-bearing
constraint.

## What it is

The half of the compounding loop distill lacks: every output today (`report`,
`research-brief`, `synthesize`) is terminal. `ask` adds the lightweight query
verb, and `--save` lets a good answer become corpus -- so the next question
starts from a richer base ("day 1 basic, day 100 an asset").

```
distill ask "which entailment checker should we use?" --topic claim-verification
distill ask "..." --topic t --save        # promote the answer into the corpus
```

## Design decisions

1. **Retrieval is the shipped lexical rank, not new machinery.**
   `search_corpus(config, topic, query)` (the same path `find_insights` uses)
   selects the top K=6 artifacts; bodies are read frontmatter-stripped and
   capped (~6K chars each) so the context stays bounded. No embeddings, no
   index -- invariant 2 stands.
2. **Grounded-only answering with mandatory citations.** The prompt carries
   `DERIVED_CONTENT_RULES` (retrieved insights are *second-hop untrusted
   content* -- a poisoned source must not steer the answer) and requires every
   claim to cite its source by bracketed stem; when the corpus doesn't cover
   the question, the correct answer is "the corpus does not cover this",
   stated plainly.
3. **The answer is an artifact with receipts.** `answers/<slug>_Answer.md`
   with the question, the cited-source list as `[[wiki-links]]`, and full
   provenance (`prompt_id: ask.v1`, model). The write-time verify hook runs
   against the concatenated retrieved bodies; the `_Verify.json` sidecar
   lands beside the answer either way.
4. **`--save` is strict by definition.** Invariant 8: an answer with *any*
   unsupported load-bearing claim is refused promotion -- the Answer.md and
   sidecar still exist (you can read why), but no `_Insights.md` is created.
   A clean answer saves as `answers/<slug>/<slug>_Insights.md` (insights-type
   frontmatter, `source: distill-answer`, `synthesis_scope: derived-answer`,
   sources listed), which the existing walkers (synthesis, claims, concepts,
   audit, CLAUDE.md counts) pick up with zero changes -- that is the
   compounding step. The saved insight keeps its sidecar, so `distill audit`
   reports derived answers' verification state like any other source.
5. **MCP parity**: an `ask(topic, question)` tool (the one deliberate tool
   addition since the 0.9.30 consolidation; it returns the answer text plus
   the artifact path -- paths-not-payloads for the sources). `--save` stays
   CLI-only until MCP write-gating (same 0.12 milestone) ships: promotion is
   a corpus mutation and agents don't get it silently.

## What this deliberately is not

Not a chat loop (one question, one artifact, exit); not RAG-with-an-index
(retrieval is the lexical rank over pre-compiled pages); not a synthesis
replacement (K=6 focused artifacts, not the whole corpus). The failure mode
this design exists to prevent is the documented one: "the AI writes something
slightly wrong, you save it back, and the next answer quietly builds on a
mistake" -- hence verify-before-save, not verify-after.
