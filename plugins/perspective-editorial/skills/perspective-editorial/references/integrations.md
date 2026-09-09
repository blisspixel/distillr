# Optional adapters

The full editorial procedure can run using the host's research and document
tools. None of these integrations is needed to install or use the skill. Do not
search unrelated repositories for API keys, activate servers, download models,
or install applications simply because an adapter is described here.

## Distillr

Use an already available `distill editorial --help` to discover whether the
installed version has the editorial commands, introduced in Distillr 0.20.0.
Older released versions do not have them. Do not invent
a successful invocation if the command is absent.

Initialize a Distill-specific profile at a new private path with
`distill editorial init --perspective /absolute/private/perspective.toml`.
Map the standalone profile's topics, target length, revision bound, and complete
`[author]` section into it. The standalone `[workflow]` section is host guidance
and is not accepted by Distill's strict schema. Keep the two files separate.
Review local model and source settings in the initialized Distill profile.

For an explicit no-metered run with an installed local model:

```text
distill --cost-mode no-metered editorial preview --perspective /absolute/private/perspective.toml --workspace /absolute/private/editorial
distill --cost-mode no-metered editorial run --perspective /absolute/private/perspective.toml --workspace /absolute/private/editorial
```

Local inference still fetches current sources. Only select an exact installed
Ollama or LM Studio model. A failed local run does not authorize paid fallback.
Local routing uses that model for all passes; it does not satisfy an explicit
requirement for a different rewrite model.

When the user permits paid inference, Distill can enforce `[budget]` settings
such as `weekly_usd = 5.0`, `per_run_usd = 2.0`, and `allow_metered = true`.
Inspect `preview`, configure explicit model slugs, and use one shared absolute
workspace for every perspective spending the same allowance. Omit the global
no-metered flag only when paid use is authorized. The ledger reserves request
ceilings before submission and conservatively retains costs for uncertain
failures. It covers those Distill model calls, not other tools or host charges.
Use a dedicated provider key cap as an additional bound; never raise it.

`distill editorial capture /absolute/private/receipts` captures sources without
model inference. Pass `--perspective` when using a nondefault profile.
`distill editorial run --receipt-dir /absolute/private/receipts` accepts an
existing receipt packet. Arbitrary Markdown is not a receipt packet: follow
the installed `SourceReceipt` schema, retaining URLs, dates, exact text, source
IDs, content hashes, and supplied-evidence provenance. Prefer native capture
when a validated receipt adapter is unavailable. Do not claim a run succeeded
unless its manifest reports completion and the output files exist.

## Other research or model tools

Prefer available local inference or a route whose included-plan authentication
and incremental billing can actually be established. Copilot credits, a CLI
login, and the existence of an API key do not prove no-metered usage. A host's
native tool has the host's cost policy, not this skill's invented allowance.

Before an external metered tool call, require an authorized route and an actual
budget controller with current prices, maximum output, a pre-call reservation,
shared persistent accounting, and fail-closed handling of unknown prices and
ambiguous failures. If unavailable, leave the paid step unexecuted. Do not use
ad hoc direct HTTP calls and estimate the cost afterward.

For model selection, compare current provider catalogs, endpoint pricing,
availability, context size, and an editorial sample. Do not choose a model only
because it leads a coding benchmark. Prefer a capable economical reader and
critic, a strong drafting model, and a different non-Anthropic writer when
required. Record actual model identities. No model choice establishes that text
has, or has removed, a statistical watermark.

## Retonr

Use only if the user selects an installed native Retonr executable or an exposed
supported adapter. Inspect its help and version first. The inspected development
CLI exposes `check` and `model`; it does not expose a rewrite or profile command.
Do not invent `retonr rewrite`.

Distill's optional `--retonr /absolute/path/to/retonr` integration runs a native
candidate check and validates the result envelope, hashes, and status. Abstention
blocks its approved export. A large factual rewrite can correctly abstain
because it changed a protected value, so preserve the reasons for inspection.

Retonr's internal Rust `GroundedRewriteService` accepts `style_context`, source,
protected terms, and a rewrite mode. It is an integration seam, not a callable
host tool merely because source code exists. A future exposed adapter can map
the profile's voice, rules, and authorized examples into style context, preserve
names, numbers and URLs, and return a validated candidate and record. Apply it
after factual revisions as a constrained style pass, then re-review the result.
The mandatory whole-article rewrite remains useful without Retonr.
