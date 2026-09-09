# Editorial model research on September 9 2026

The initial recommendation is to use an installed local model when it is
explicitly configured and passes the editorial checks. For paid runs, start
with Gemini 3.7 Flash for reading, Sonnet 5 for a provisional first draft,
GPT-5.6 Sol for rewriting, and Gemini 3.7 Flash for critique. All routes remain
configurable and metered use requires explicit consent and a dollar budget.

This recommendation comes from current provider documentation and a small
live writing comparison. It is a starting point for this workflow, not a
general ranking or a claim that one model is the best writer.

## Candidates and price evidence

The [OpenRouter model catalog](https://openrouter.ai/api/v1/models) was fetched
on September 9, 2026. Rates below are listed dollars per million tokens before
cache discounts. Actual endpoint rates, reasoning tokens and billing can differ.
Distill admits calls with its conservative registered ceilings and records the
provider's reported cost. It never authorizes spend from this table alone.

| Model | Listed input | Listed output | Potential role |
|---|---:|---:|---|
| `openai/gpt-5.6-luna` | $0.20 | $1.20 | Low-cost reading, ideas and rewriting |
| `google/gemini-3.7-flash` | $0.75 | $3.75 | Independent structured critique with room for reasoning |
| `anthropic/claude-sonnet-5` | $2.00 | $10.00 | Provisional draft, followed by another model's rewrite |
| `openai/gpt-5.6-sol` | $2.00 | $10.00 | Optional more expensive editorial comparison |
| `anthropic/claude-opus-5` | $5.00 | $25.00 | Premium candidate; not necessary for the initial small budget |
| `moonshotai/kimi-k2.6` | $0.95 | $4.00 | Alternative worth a later style evaluation |
| `deepseek/deepseek-v4-pro-0813` | $0.57948 | $1.73844 | Lower-cost alternative requiring price registration and evaluation |

Catalog prices and model-page endpoint offers did not always agree. For example,
the [Kimi page](https://openrouter.ai/moonshotai/kimi-k2.6) displayed discounted
endpoint offers below the catalog rate. The [Gemini page](https://openrouter.ai/google/gemini-3.7-flash)
also shows promotional pricing and endpoint-specific options. Avoid deriving a
hard budget from a search snippet or a displayed cheapest-endpoint offer.

[OpenRouter rankings](https://openrouter.ai/rankings) are usage measurements,
including a writing category, rather than blind editorial evaluations.
[Anthropic's Sonnet announcement](https://www.anthropic.com/research/claude-sonnet-5)
describes capabilities but does not establish a best blogging model. The exact
task must be tested, including faithfulness and the final editing pass.

## Live writing comparison

Four models received the same four primary-source receipts and the same brief:
write a 350 to 450 word AI news opening, from a practical enthusiast's
perspective, explaining why image edits, lab experiments, mathematical proofs
and cyber-defense claims require different checks. No model received another
candidate's response. The output limit was 2,000 tokens and retries were disabled.
The comparison used a shared `$0.80` run cap under the `$5` weekly ledger.

| Model | Reported spend | Elapsed seconds | Observed result |
|---|---:|---:|---|
| Sonnet 5 | $0.047556 | 18.8 | Coherent narrative, but asserted that public verification had not happened; the supplied sources did not establish that absence |
| Gemini 3.7 Flash | $0.016996 | 16.2 | Returned an incomplete excerpt after consuming nearly the entire output allowance |
| GPT-5.6 Sol | $0.100840 | 14.8 | Concrete proposed tests and clear organization; language about independent acceptance needed careful qualification |
| GPT-5.6 Luna | $0.003918 | 12.1 | Coherent, economical excerpt; kept the mathematical conclusion framed as the company's claim and included the cyber-defense example |

Total comparison spend was `$0.16931015`. One sample per model cannot establish
robust preference, reliability or prose quality across topics. The evaluation
above is an editorial reading of visible output, not a hidden numerical score.
The Sol result also illustrates why listed catalog prices must not be substituted
for observed billing. Conservatively admitted requests remained within budget.

The Gemini result prompted a concrete implementation fix: preserve the provider's
completion reason and refuse incomplete editorial stages. Critique receives a
larger output allowance than the short comparison. The first draft is always
rewritten, and the paid refinement route must be non-Anthropic, as requested.
This is an editorial control, not a claim to detect or remove a watermark.

Longer workflow trials changed the initial economical recommendation. Luna
returned empty responses on two longer requests despite still answering a short
probe. Gemini research, Sonnet drafting, Sol rewriting and Gemini critique
completed the full workflow twice, at about `$0.34` per run on four receipts.
That combination is the shipped paid example, with a `$2` per-run ceiling and
`$5` weekly ceiling. Both are admission limits, not predicted prices.

Luna remains a low-cost candidate to test on an operator's own article briefs.
Set `research_model` and `refinement_model` to `openai/gpt-5.6-luna` to compare it.
An installed Ollama `gemma4:e2b` also completed a zero-dollar routing probe, but
used the short output allowance on unfinished reasoning. That proves local
connectivity and accounting, not adequate editorial quality.

The live critique also caught a request-shaping issue: an image-price filter
excluded eligible multimodal endpoints on a text-only request. Token ceilings,
zero extra per-request fees and the privacy constraints remain enforced. Exact
evidence checks exposed miscopied critic quotes; the workflow now permits one
budgeted critic repair before spending on another article revision.

## Sources for the sample

The reading packet covers four primary announcements:

- [ChatGPT Images 2.5](https://openai.com/index/introducing-chatgpt-images-2-5/), September 8.
- [GPT-5.6 Sol in quantum computing experiments](https://openai.com/index/codex-quantum-computing-experiments/), September 8.
- [The Navier Stokes announcement](https://openai.com/index/navier-stokes-solution/), September 8.
- [Google's Fairwind Program](https://blog.google/innovation-and-ai/technology/safety-security/fairwind-program/), September 2.

The native RSS capture worked after selecting a current CA bundle for this
Windows validation process. Some publisher pages returned HTTP 403, so their
full text was captured through the external research browser and supplied
through the explicit receipt adapter. The records preserve their supplied
provenance. The example therefore validates the editorial workflow on current
receipts; it does not claim that every publisher allowed native page capture.

The final sample is **What the Latest AI News Lets Us Test**, dated September 9.
Its full research-to-article run cost `$0.33246075`; the final editorial rewrite,
critique and exact-evidence repair added `$0.18566075`. Earlier comparisons and
failed trials are also charged, rather than hidden from the validation total.
The completed Markdown has 1,025 words. Its three-page DOCX was rendered using
installed Microsoft Word and every page was inspected. The exporter removes
inherited title borders and preserves actual hyperlinks.

All live validations added `$1.47683478` in reported provider usage. The weekly
workspace ledger conservatively accounts for `$1.86382428`, including failed
requests without conclusive billing evidence. The difference is retained in
the allowance; it is not automatically refunded or presented as actual billing.

## Writing and integration boundaries

Use [NN/G's web-writing findings](https://www.nngroup.com/articles/concise-scannable-and-objective-how-to-write-for-the-web/)
as editorial guidance: a useful opening, readable headings, specific prose and
limited promotional language. Mechanical bans on punctuation cannot replace
reviewing an argument, its evidence and its voice.

Retonr currently exposes deterministic checks on proposed plain-text candidates.
Code inspection also found an internal Rust `GroundedRewriteService` accepting
`style_context`, which provides the future person/company voice integration
point. Its CLI exposes only `check` and `model`; rewrite and profile commands are
not yet implemented. Distill integrates `check`. Local Ollama and LM Studio
routes are no-metered by topology; plan-quota
workers need their own included-plan billing proof and qualification first.

The native Retonr CLI was built and the adapter passed an unchanged-text control.
The sample's substantial draft-to-final revision triggered `protected_value_changed`
and abstention, as its strict fidelity policy permits. The delivered sample uses
the model rewrite and evidence-review path with Retonr disabled. This check is
most suitable for constrained candidate edits until Retonr exposes its rewriting
service and style profiles through a supported command contract.
