# claim-verification -- distillr research corpus

This directory is a distillr research corpus on **claim-verification**: plain-Markdown per-source insights, cross-source synthesis, and a concept/entity playbook. Every file is greppable -- no database, no schema. Read it directly (`grep`, `cat`, `ls`) or query it through distillr's MCP server.

## Contents

- **6 sources (6 papers)** analyzed into `_Insights.md` files under `papers/`, `channels/`, and `sites/`.
- Last refreshed: 2026-06-11T12:48:44Z

## Ask me about

- What does the corpus say about claim-verification?

## Querying this corpus over MCP

distillr exposes the corpus to agents through these tools (`topic` is `claim-verification`):

- `find_insights(topic, query)` -- semantic search across the topic's per-source insights
- `read_insight(path, section=None)` -- read one insight file, optionally a single section
- `find_concepts(topic, query='', kind='', contested_only=False)` -- query the concept/entity playbook
- `read_concept(path)` -- read one concept or entity note
- `research_gaps(topic)` -- what the corpus is thin on, plus suggested next actions
- `concept_history(topic, slug)` -- version history of a concept note
- `concept_diff(topic, slug, ts_a='', ts_b='')` -- structured diff of a note across versions

<!-- Regenerated on every topic refresh. Do not edit by hand. -->
