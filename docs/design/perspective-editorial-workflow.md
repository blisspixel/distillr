# Perspective driven editorial workflow

Status: opt-in CLI extension in release `0.20.0`.
Research reviewed September 9, 2026. This release was explicitly requested while
the trust and evaluation backlog remains outstanding. It changes no default
research route or corpus contract.

## Outcome

A person or company can maintain a private editorial perspective, follow a
bounded set of current topics, and produce an evidence-backed blog in Markdown
and DOCX. An author can inspect the reading notes, rejected ideas, outline,
draft, independent rewrite, critiques, source receipts, and actual model spend.
The workflow does not publish or promote its prose into independent evidence.

The existing README and roadmaps place Distill's value in current-source
capture, verifiable research, and recurring refresh. This feature is a consumer
of that research layer. Perspective controls relevance, emphasis and voice; it
does not change source facts. Drafts live outside the native corpus.

## Research and decisions

OpenRouter's [rankings](https://openrouter.ai/rankings) measure usage. They are
useful for finding candidates, but are not an editorial-quality benchmark.
The [model catalog](https://openrouter.ai/api/v1/models) supplies concrete slugs,
token prices and supported request parameters. The dated comparison in
[the research note](../research/editorial-models-2026-09-09.md) explains the
candidate roles and live validation.

The workflow reuses Distill's OpenRouter provider, which requests no data
collection and Zero Data Retention. Its
[provider price ceilings](https://openrouter.ai/docs/guides/routing/provider-selection)
constrain token rates. Its actual usage records retain reported billed cost.
[Key spending limits](https://openrouter.ai/blog/tutorials/team-spend-controls-setup/)
provide a separate account-side defense. A price estimate alone is insufficient:
the workflow reserves a conservative amount before each model request.

For writing, [NN/G's web-reading research](https://www.nngroup.com/articles/concise-scannable-and-objective-how-to-write-for-the-web/)
supports clear conclusions, useful headings, concise prose, and restraint in
promotional language. The implementation asks models to judge the quality of
the argument, the evidence and the voice. Character restrictions enforce the
author's literal punctuation preferences, without claiming to measure quality.

Retonr's local README and implemented `crates/cli/src/check.rs` were inspected.
Its current `check SOURCE CANDIDATE --format json --fail-on-abstain` validates a
caller-supplied plain-text revision. Its internal Rust `GroundedRewriteService`
in `crates/app/src/grounded.rs` can generate grounded candidates with
`GroundedRewriteRequest.style_context`, protected terms, a rewrite mode,
cancellation and a deadline. The current CLI exposes `check` and `model`,
without a public rewrite or style-profile command. The adapter calls this
existing check, with a fixed argv,
no shell, a timeout, and no inherited provider keys. Markdown is passed as text;
this is not a claim of qualified Markdown rewriting. Abstention leaves drafts
available and prevents the final output pair.

## Execution and artifacts

1. Validate the TOML perspective, limits, source scope and route policy.
2. Prefer the explicitly configured, installed local model on a loopback endpoint.
   Otherwise admit only explicitly enabled and registered OpenRouter routes.
3. Capture current RSS items and exact supplied pages using Distill's public
   HTTPS and HTML extraction boundaries. Retain timestamps, content digests,
   failures and truncation. Exact URLs receive capture slots before feed items.
4. Read the evidence, propose and critique three ideas, select an angle and plan
   the argument and takeaway. Previous article titles inform novelty judgment.
5. Draft with the configured writer. Always rewrite the full draft with the
   refinement route. The paid refinement route must be non-Anthropic.
6. Review factual support, freshness, perspective, usefulness, structure, style
   and claim coverage separately. Require exact article substrings and exact
   supporting receipt excerpts. Model judgment assesses entailment and coverage.
7. Revise and review up to the explicit limit. Missing evidence, unresolved
   criticism or malformed model output prevents an approved article.
   A review with miscopied evidence gets one bounded critic repair, with the
   same exact-source checks and request budget, before revising the article.
8. Optionally check the revision with Retonr, then export unbranded Markdown and
   DOCX with one title and real hyperlinks. Mark it ready for human review.

Every run has a unique private directory. Its manifest contains the perspective
digest, route identities, budget, status, spend and article digest. The private
brief snapshot contains the author context and actual evidence shown to models.
The default shipped example contains no real author or company information.
The Git ignore rule already covers `private/`, including all runs and receipts.

`--receipt-dir` accepts explicitly supplied recent receipt JSON files from an
earlier capture or external research agent. It validates bounded size, URL,
identity, text digest, uniqueness and capture age. Supplied provenance remains
visible: a hash is an integrity check, not publisher authentication. Publication
date and capture date remain separate. A fresh fetch never makes old news new.

## Budget contract

One `budget.jsonl` is shared across perspectives and processes in the workspace.
Weeks start Monday at 00:00 UTC. Each metered request uses both the existing
per-run `CostTracker` admission and a durable weekly reservation. The read,
check and append happen under a cross-process lock, with durable writes.
Unknown prices and ambiguous billing routes fail closed. No model downloads,
paid search tools, image generation, automatic credit purchase or top-up occurs.

Reported usage settles the reservation. A crash before accounting leaves the
full reservation charged against the available allowance. Pending reservations
carry across weeks; a request spanning a week boundary is conservatively counted
in both weeks. Corrupt, truncated or inconsistent histories stop new spend.
There is no automatic reservation refund or reset command.

The cap covers inference routed through this workspace. It cannot coordinate
other programs or copies of the workspace that spend with the same key. Use one
workspace and a dedicated provider key with a provider-side limit. Credit
purchase fees, taxes, electricity, and subscription fees are outside token cost.
This implementation never purchases credits.

Local inference has no API bill. A local model can still be slow or produce a
draft that fails review. A configured local route that fails during execution
does not automatically escalate to paid inference. The operator can explicitly
select `--paid-only` under the same caps. Plan-quota CLI adapters remain future
work until their billing preflight, support statement, usage ledger, scratch
manifest and evaluation gates exist. Copilot is not an included-plan default.

## Verification and next increments

Unit and workflow tests cover concurrency, restart, rollover, failed requests,
corrupt ledgers, explicit metered consent, global no-metered refusal, local
selection, exact citations, invented evidence, review limits, unbranded DOCX,
private defaults, and Retonr abstention. Live model comparisons and the first
sample are recorded separately from deterministic tests.

The next increments are a mature-corpus receipt selector, per-topic editorial
queues, digest-bound resume, calibrated local quality profiles, qualified quota
workers, and Retonr rewriting when its public contract exists. Scheduling uses
the operating system today; no background scheduler is silently installed.
No detector-score optimization or watermark-removal claim is made.

The future Retonr rewrite adapter should map the perspective's voice, rules and
authorized style examples into `style_context`, pass cited URLs and declared
company terms as protected values, and preserve its returned `RewriteRecord`.
Run that constrained style pass after factual revisions, then repeat the article
evidence checks before export. Bind it to an explicit local runtime and artifact
manifest; do not infer that an arbitrary `InferenceBackend` is unmetered.
