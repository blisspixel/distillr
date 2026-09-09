# Private perspective and budgeted blog writing

`distill editorial` turns current publisher receipts into a reviewed blog draft.
It saves the article as Markdown and DOCX, with reading notes, ideas, outline,
drafts, critiques and cost evidence alongside it. It never publishes.

For the same editorial process using an agent host's existing tools, see the
[standalone editorial skill](portable-editorial-skill.md). It works without
Distillr, with optional adapters for Distill's budget enforcement and Retonr.

## Configure a private perspective

```bash
distill editorial init
```

Edit `private/perspective.toml`. The file describes the writer, role, company,
audience, perspective, voice, style rules and optional authorized writing
examples. Personal perspectives, research receipts and generated articles stay
under the Git-ignored `private/` directory. Only the
[generic default example](../distill/editorial/default-perspective.toml) ships.
Keep API keys in the existing environment or `.env`, outside the perspective.
When you enable a cloud route, its prompt includes the private author context
and supplied writing examples. Only include context you want that route to use.

The default topic is AI news. Configure the RSS feeds and exact page URLs for
your topics. Discovery is bounded to that source set. It is not a claim to cover
the entire web. Missing dates and failed captures remain visible in the notes.

## Prefer local inference

Set `routes.local_provider` to `ollama` or `lmstudio` and `routes.local_model` to
an exact installed model. Distill checks the loopback service for that model,
then uses it for all editorial passes. It does not download one automatically.

```bash
distill --cost-mode no-metered editorial preview
distill --cost-mode no-metered editorial run
```

Current public sources are still fetched in local mode. Included-plan CLI
workers are not yet qualified Distill providers, so they are not silently
treated as free alternatives. If a selected local model fails, the run stops
with its work saved instead of escalating to an API.

## Allow a controlled paid fallback

To allow the named OpenRouter models, explicitly set:

```toml
[budget]
weekly_usd = 5.0
per_run_usd = 2.0
allow_metered = true
```

Then inspect and run:

```bash
distill editorial preview
distill editorial run
```

The paid example uses Gemini 3.7 Flash for reading, Sonnet 5 for the first draft,
GPT-5.6 Sol for a mandatory full rewrite, and Gemini 3.7 Flash for critique. Change
the concrete model slugs in `[routes]` to compare alternatives. The refinement
model must be non-Anthropic. The [model research](research/editorial-models-2026-09-09.md)
explains current candidates and tradeoffs. No metered model is selected without
the opt-in. Global `--cost-mode no-metered` overrides that opt-in.

For a deliberate paid validation even when a local model is available:

```bash
distill editorial run --paid-only
```

Each request must fit the remaining per-run and weekly allowance before it is
sent. All perspectives in the same `--workspace` share the weekly ledger.
Weeks begin Monday at 00:00 UTC. Unknown token prices are refused. Failed or
interrupted submissions retain conservative costs; corruption stops new spend.
`preview` reports spent-or-reserved dollars and pending reservations.

Keep one workspace for the spending allowance. Other programs and workspace
copies cannot share its ledger automatically. Also set a dedicated OpenRouter
key limit and disable provider auto-top-up. Existing key limits are never raised.
The dollar cap covers model inference, not credit purchase fees or subscriptions.

## Capture and agent handoff

Capture current receipts without invoking a model:

```bash
distill editorial capture private/news-receipts
distill editorial run --receipt-dir private/news-receipts
```

The destination must be new. The default `run` command fetches sources itself;
`--receipt-dir` instead uses the explicit, recent JSON packet you supply.
An agent can also supply receipt JSON following `SourceReceipt` in
`distill/editorial/sources.py`. Exact content hashes, source IDs, public HTTPS
URL syntax, capture age and size limits are checked. These files are labeled
supplied evidence, not independently authenticated publisher records.
`--json` returns machine-readable command results. Use the Python
`build_article` service for composition inside a larger agent workflow.

## Review outputs and use Retonr

Each successful run writes under `private/editorial/runs/<run-id>/`:

- `article.md` and `article.docx`: the clean final pair, ready for human review.
- `reading.md`, `ideas.md`, `outline.md`, `draft.md`, `rewrite.md`: editorial work.
- `review-*.json`, `checks-*.json`, `revision-*.md`: critiques and bounded revisions.
- `receipts/`, `brief.json`, `manifest.json`, `usage.json`: evidence and accounting.

All seven model verdicts must pass, and the cited claim excerpts must match the
captured evidence. These checks assist review; semantic judgments can be wrong.
Each review permits one budgeted repair of miscopied evidence before requesting
another article revision. Both critic responses remain available for inspection.
Failed runs retain drafts and a failed manifest without an approved article.
Re-running starts a new run, retains previous costs, and uses past article titles
to inform idea selection. Automatic resume is not implemented.

Retonr's current CLI checks a supplied candidate. Its internal Rust
`GroundedRewriteService` accepts style context, but the CLI does not yet expose
that rewriting service or a style-profile command.
Build or supply its existing native CLI, then opt in:

```bash
distill editorial run --retonr /absolute/path/to/retonr
```

This runs `retonr check` on the original and revised Markdown as plain text.
Its abstention blocks the approved output. It does not certify Markdown
preservation or remove statistical watermarks. The separate model rewrite
already happens whether or not Retonr is installed.

## Recurring runs

Use cron, launchd or Windows Task Scheduler to run the same command from a known
working directory. Pass absolute `--perspective` and `--workspace` paths so every
run shares its ledger. For example, a weekly scheduled action can execute:

```bash
distill editorial run --perspective /absolute/private/perspective.toml --workspace /absolute/private/editorial
```

No task is installed automatically. Exit code `6` means a budget admission
refusal. Review the manifest and `preview` before retrying. Do not delete the
ledger to recover a crashed run: an uncertain request may still be billed.

Design and boundaries: [editorial workflow](design/perspective-editorial-workflow.md).
