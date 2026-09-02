# Install and setup

Recommended path and first-run guidance live in the
[project README](../README.md). This page covers alternate installers, keys,
local models, updates, and shell completions.

## Recommended: `uv tool`

[`uv`](https://docs.astral.sh/uv/) installs the CLI into an isolated, on-PATH
environment in one command:

```bash
uv tool install distillr
distill --version
distill --cost-mode no-metered init
distill --cost-mode no-metered papers "temporal knowledge graph" --topic tkg --limit 5 --preview
```

Try before installing: `uvx --from distillr distill --help`. Ingestion needs a
one-time Chromium install, so `uv tool install` is the path for real runs.

**Platforms:** Windows, macOS, and Linux. CPython 3.12 through 3.14 are the
supported runtime matrix. Python 3.15 is still a release candidate and has an
advisory Linux CI lane; Windows installation currently waits on an upstream
`pywin32` CPython 3.15 wheel. Local models run on consumer GPUs via Ollama or LM
Studio.

## Guided setup (`distill init`)

`init` creates `.env`, guides cloud or local provider choice, installs Chromium
when needed, and ends with a ready or not-ready verdict. The recommended
invocation permits local validation and refuses API-billed or ambiguous
provider checks. If you choose a cloud API, run
`distill --cost-mode paid-ok init` only when you intend its minimal live
key-validation request. That request can be billed and is recorded in the local
ledger. Local readiness requires a successful loopback provider probe and an
exact configured model in the provider inventory. Both setup paths are
no-TTY-safe. Full flags: [usage.md](usage.md#setup-distill-init).

Preview-first paper runs can fetch current public candidates and use an allowed
model route to rank them, but they do not ingest papers or write corpus
artifacts. `no-metered` fails closed if no proven no-metered analysis route is
available. Remove `--preview`, choose an explicit limit, and permit a metered
route only when you are ready to commit the run.

## Other install paths

### Repository installers

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.ps1 | iex"
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.sh | bash
```

These commands download and execute the current installer from this repository.
Review the linked script first when your environment requires pinned or audited
installation input. Open a new terminal after the installer finishes.

### Virtual environment or source checkout

```bash
python -m venv .venv
# Windows (PowerShell):   .\.venv\Scripts\Activate.ps1
# macOS / Linux:          source .venv/bin/activate
pip install -e .              # from a source checkout, or: pip install distillr
playwright install chromium
distill --cost-mode no-metered doctor
```

### pipx

```bash
pipx install distillr
playwright install chromium
distill --cost-mode no-metered doctor
```

### Bare pip

```bash
pip install distillr
playwright install chromium
distill --cost-mode no-metered doctor
```

**Windows note:** If you use a system Python under `C:\Program Files\Python...`
without admin rights, bare `pip` installs to your user directory. The CLI may
land in a Scripts folder that is not on `PATH`. Prefer venv, pipx, or uv, or
add `%APPDATA%\Python\Python312\Scripts` (adjust version) to your user PATH and
restart the terminal.

## Corpus location and keys

Default library path is `~/.distill/library/` (`<repo>/library/` from a source
checkout). Override with `DISTILL_OUTPUT_DIR`. User-facing report and export
files go to the `output/` directory beside that library. Despite its historical
name, `DISTILL_OUTPUT_DIR` selects the library root, not the export directory.

Cloud routes read keys from `.env` in your working directory (copy from
`.env.example`); set only the providers you intend to use:

The installed executable location does not control this lookup. For example,
running `distill` from `C:\GitHub\distillr` reads
`C:\GitHub\distillr\.env` even if `distill.exe` lives under a user tool
directory. If you run from another directory, put `.env` there or export the
variables in the shell. This repository ignores `.env`, `.env.local`, and
environment-specific `.env.*` files; only `.env.example` is tracked.

```bash
XAI_API_KEY=xai-...             # Grok models (default analysis)
GEMINI_API_KEY=AIza...          # Gemini analysis route + Deep Research reports
ANTHROPIC_API_KEY=sk-ant-...    # Claude API route (metered, explicit opt-in)
OPENROUTER_API_KEY=sk-or-...    # Multi-model route (metered, explicit opt-in)
```

Pick or change the analysis route with the CLI (writes `.env` only on `set`):

```bash
distill provider                              # show active provider + model
distill provider list gemini                  # known models + prices
distill provider set gemini gemini-3.7-flash  # persist default route
distill --provider gemini --model gemini-3.5-flash-lite papers "..." --limit 5
```

The Anthropic API route is implemented but not a calibrated default. Select it
explicitly, permit metered spend, and review the estimate before running it.
OpenAI model IDs are retained only for cost-registry and future-routing truth;
OpenAI is not currently a runnable Distill provider.

### OpenRouter optional metered route

OpenRouter is useful when a direct-provider quota is unavailable and local
inference is not practical. Create a key at
[OpenRouter](https://openrouter.ai/settings/keys), add it to the working
directory `.env`, and select one concrete model:

```bash
distill provider set openrouter x-ai/grok-4.6
distill --cost-mode paid-ok doctor
```

Distill requires a lowercase `author/model` slug. It deliberately rejects all
`openrouter/*` router models, including `openrouter/auto` and
`openrouter/free`, moving `-latest` aliases, and colon variants such as `:free`.
This preserves a stable model identity for evaluation and cost records.
OpenRouter has no Distill default model and is never added to the automatic
route ladder.

The adapter requests `data_collection=deny` and Zero Data Retention routing by
default. Set `DISTILL_OPENROUTER_ZDR=false` only if you intentionally accept a
broader upstream provider pool. This setting cannot disable ZDR already required
by your OpenRouter account or guardrails. OpenRouter and its upstream provider
still receive the prompts sent through this route, so review their policies for
your chosen model. `DISTILL_COST_MODE=no-metered` always blocks OpenRouter.

Distill checks OpenRouter's no-cost endpoint catalog before inference. This
selects the token-limit field supported by the eligible upstreams and avoids
sending an optional temperature when none of them supports it, while retaining
strict parameter enforcement. Calls in one Distill run share a random
`session_id`, derived one way from the local run id, for stable upstream routing
and prompt-cache locality. Distill does not enable OpenRouter's beta response
caching.

For registered models, Distill sends an upstream per-token price ceiling,
preauthorizes each bounded attempt against configured workflow budgets, and
records OpenRouter's exact reported billed cost after the call. An unregistered
model may run only without a hard dollar budget because Distill cannot prove a
pre-call ceiling. An OpenRouter key spending limit is a useful independent
account-side guard. The no-inference key doctor reports that limit and its
remaining allowance when OpenRouter supplies them.

Full provider command reference: [usage.md](usage.md#provider-and-model-route).

## Local models (Ollama / LM Studio)

```bash
ollama pull qwen3.5:27b
distill provider set ollama qwen3.5:27b
distill --cost-mode no-metered doctor
```

### Measuring and choosing a local model

```bash
distill bench                        # measure every installed model on this machine
distill roles                        # see roles and what this machine suggests
distill roles set deep qwen3.5:27b   # pin a model to a role
distill --role deep papers "..." --topic t
```

`distill bench` reports prompt-processing and generation rates, load time, and
the projected wall clock for a typical paper, so you can pick a model knowing
what it costs in time rather than guessing from its size. Size is a poor
predictor: a mixture-of-experts model can decode several times faster than a
smaller dense one.

After a bench, `distill papers --preview` prints `$0.00` and a duration such as
`~1h15m on this machine`. Hours are expected on local hardware. Local models
keep getting faster; the same command gets cheaper in time without changing the
`$0` spend. Persist the route so you do not have to pass it every time:

```bash
distill --cost-mode no-metered provider set ollama qwen3.5:27b
```

A bare `distill papers` still follows `.env`. If `DISTILL_PROVIDER` is unset,
the default cloud route can spend. `--cost-mode no-metered` refuses that
instead of charging.

Roles name which model to use when. `deep` is suggested from the server's own
capability report -- whether a model produces a reasoning trace -- and `fast`
from measured speed once `distill bench` has run. `unfiltered` is never
suggested, because nothing the server reports distinguishes it; assign it
yourself if you need it.

A role only changes which model reads the source. Prompts, the write-time verify
gate, and receipt discipline are identical for every role.

Local mode still uses fresh sources. `DISTILL_PROVIDER=ollama` or
`DISTILL_PROVIDER=lmstudio` changes the model that analyzes fetched receipts;
it does not answer from model pretraining alone. Discovery and ingest still
fetch current public sources such as arXiv, YouTube, feeds, sites, repos, and
local files.

## Updates

```bash
distill update            # upgrade in place (uv tool / pipx / pip)
distill update --check    # report only
```

Distill also prints a one-line nudge when a new release is published (cached
daily; silence with `DISTILL_NO_UPDATE_CHECK=1`). Details:
[usage.md](usage.md#updating-distill).

## Shell completions

```bash
distill --install-completion    # bash / zsh / fish / PowerShell
distill --show-completion       # print the script
```

Includes live topic-name completion.

## Privacy of operational traffic

No outbound product analytics or usage beacons. Research, keys, and run history
stay on disk. Operational logs and prompt telemetry stay under
`library/.distill/`. The only outbound calls are the LLM or transcription APIs
you configure, update checks you do not disable, and the public sources you ask
it to fetch.
