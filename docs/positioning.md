# Where Distill sits

Three kinds of tools orbit this space, and Distill is deliberately none of them:

- **Deep Research oracles** (ChatGPT, Gemini, Perplexity) are excellent at
  one-shot answers, and the work evaporates after each session. No corpus, no
  receipts you can re-check, nothing that compounds. Distill is the engine
  under that pattern: every run leaves transcripts, extracted paper text,
  per-source insights, and cross-source synthesis on disk, refreshable on a
  cadence.
- **Grounded notebooks** (NotebookLM) keep a persistent corpus, but in a silo:
  you find and feed the sources by hand, and the corpus exports to Google
  Docs/Sheets only. Distill *finds* the sources against your goal, and the
  corpus is plain files you own.
- **LLM-wiki maintainers** (the post-Karpathy wave of agent-curated Markdown
  vaults) assume you already have the content and tidy it. Distill is the
  acquisition half they leave out: goal-aware discovery across papers, videos,
  and operator-trusted sites, direct ingestion for X and other supplied
  sources, transcript-grade capture, and provenance on every claim, producing
  exactly the kind of vault those tools maintain.
- **Academic literature tools** (Elicit, Semantic Scholar, scite, Consensus)
  are stronger for pure paper search, citation graphs, and systematic review.
  Distill treats papers as one source type inside a broader corpus that also
  holds talks, vendor docs, and posts.

The short version: those are **report and search layers**; Distill is the
**corpus layer underneath repeated research** (capture, per-source insights,
cross-source synthesis, refresh, receipts). Its human analogue is a research
librarian, literature analyst, and research desk. Plain Markdown is the
substrate, not the moat: anyone can write Markdown. The durable advantage is
goal-aware acquisition, inspectable curation decisions, receipt-bound trust,
and a field model that becomes more useful across refreshes.

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
