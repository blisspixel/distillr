# Where Distill sits

Several kinds of tools overlap this space. Distill focuses on maintaining an
inspectable corpus across repeated research runs:

- **Deep Research tools** (ChatGPT, Gemini, Perplexity) overlap with discovery
  and cited reporting. Distill's product commitment is a local corpus with
  captured source text, per-source insights, verification receipts, and
  repeatable refresh workflows. Compare those properties directly rather than
  assuming another product cannot retain or export its research.
- **Grounded notebooks** also overlap with discovery. Google's current
  [notebook documentation](https://support.google.com/gemininotebook/answer/16215270?hl=en)
  describes web and Drive source search, Deep Research, source import, and
  automatic Drive synchronization.
  Manual source collection is therefore not the distinction. Distill keeps
  its native corpus and receipts in operator-owned files and exposes them
  through CLI, MCP, and export interfaces. This comparison was checked on
  September 13, 2026.
- **Markdown research and wiki workflows** also include acquisition.
  [Khoj](https://github.com/khoj-ai/khoj) documents web and document research,
  local models, Obsidian integration, and recurring tasks;
  [Obsidian Web Clipper](https://github.com/obsidianmd/obsidian-clipper)
  captures durable Markdown. Distill should demonstrate the combined capture,
  verification, lineage, and refresh contract rather than claim this category
  leaves acquisition out.
- **Literature and research tools** overlap beyond paper search. Elicit's
  [August 4, 2026 Research Agent announcement](https://elicit.com/blog/introducing-elicit-research-agent)
  includes scientific, web, public, and uploaded internal sources with cited
  deliverables and persistent projects. Distill's case is the operator-owned
  corpus and inspectable evidence lifecycle across source families. Comparative
  quality requires task evidence, not a feature-list inference.

Distill is the **corpus layer underneath repeated research** (capture, per-source insights,
cross-source synthesis, refresh, receipts). Its human analogue is a research
librarian, literature analyst, and research desk. Plain Markdown is the
substrate, not the moat: anyone can write Markdown. The durable advantage is
goal-aware acquisition, inspectable curation decisions, receipt-bound trust,
and a field model that becomes more useful across refreshes. This is the
product's intended advantage; the current generation/origin gaps and missing
research-episode baseline prevent treating it as a demonstrated superiority
claim. See the [September 13 review](research/roadmap-review-2026-09-13.md).

That matters for literature review, technical research, thesis work, or a
maintained topic corpus: you can verify the receipts, watch how a topic evolves,
query the same folder through MCP from agent clients, and open it in Obsidian,
Logseq, VS Code, or plain filesystem search. Distill can build an evidence
corpus about a company, but company-specific strategic interpretation and
diligence conclusions belong to a company-analysis product rather than the
corpus layer.
Reports and briefs export to Word for stakeholder delivery
(`distill export <topic> --what report`), and paper topics export to BibTeX or
RIS for Zotero and reference managers
(`distill export <topic> --what citations`). Nothing is locked in.

## Who it is for

Distill is a terminal tool for people comfortable installing a Python CLI and
configuring one permitted model route, either a cloud key or a local provider
plus an exact model. If you want a one-click app, this is not that. The corpus
it builds is plain files precisely so the tools you already use can be the
interface.

The product doctrine and feature-admission test are in
[research-desk-doctrine.md](design/research-desk-doctrine.md).

See also the design charter in [invariants.md](invariants.md).
