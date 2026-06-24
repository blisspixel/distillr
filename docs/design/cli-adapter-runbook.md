# CLI adapter runbook

Status: accepted guidance for 0.19 adapter doctor and cross-route eval.
Researched June 18, 2026 against official docs and local CLI help.

This runbook defines how Distill should invoke local runtimes and plan-quota
coding CLIs without hidden API spend or uncontrolled writes. It covers Ollama,
LM Studio, Codex CLI, Claude Code, and Grok Build. Credit-metered CLIs such as
GitHub Copilot CLI can reuse the same scratch-manifest contract, but they are
not no-metered defaults.

## Operating rule

Official docs define the intended interface, but the installed binary is the
runtime truth. Adapter doctor must capture `--version` and `--help` output and
disable a route when a required flag is absent.

This matters in practice. OpenAI's Codex docs document `--ask-for-approval`, but
the locally installed `codex-cli 0.140.0` exposes sandboxing and JSONL output
without that flag on `codex exec`. Distill must validate flags before it builds
a command.

## Common adapter contract

- Run inside a scratch workspace, not the live corpus.
- Provide source packages by copy or read-only staging. Do not point adapter
  write access at `library/`.
- Require machine-readable output: JSON, JSONL, streaming JSON, JSON schema, or
  a scratch result manifest.
- Fail closed on malformed output, unknown auth mode, timeout, quota stop,
  missing usage metadata, or unexpected file writes.
- Remove paid API key environment variables from plan-quota subprocesses. At
  minimum: `OPENAI_API_KEY`, `CODEX_API_KEY`, `ANTHROPIC_API_KEY`, `XAI_API_KEY`.
- Scan provider config files for `api_key`, `env_key`, or provider API-key
  environment references. Presence classifies the route as metered unless the
  user selected `paid-ok`.
- Run read-only JSON auth probes when the CLI exposes them, such as
  `claude auth status --json` or `grok inspect --json`.
- Report only matched config or auth-command marker names and display paths.
  Never emit secret values from provider config files or auth command output.
- Treat support statements as structured evidence records: status, checked date,
  source URLs, required evidence, no-metered current flag, and notes. A
  plan-quota route remains blocked unless the statement is current for
  no-metered routing and the route clears eval.
- Normalize native usage through a strict `adapter-native-usage.v1` scratch
  record before writing an `adapter-result.v1` manifest. The record must carry
  token counts or native usage metadata and must stay scratch-relative.
- Record every route on the ledger even when dollar cost is zero: adapter,
  version, auth class, model when known, prompt hash, source hash, elapsed time,
  native usage signal, stop reason, and files written.
- Prefer read-only, no-tool, or plan modes until an adapter clears eval.

## Local sunk-cost routes

### Ollama

Best default for high-volume fan-out, candidate triage, cheap negative passes,
draft per-item summaries, and cross-topic clustering.

Preferred API pattern:

```text
POST http://localhost:11434/api/generate
{
  "model": "<model>",
  "prompt": "<prompt>",
  "stream": false,
  "format": <json-or-schema>,
  "keep_alive": "5m",
  "options": {
    "num_predict": 512,
    "temperature": 0.2
  }
}
```

Useful flags and settings:

- `ollama run MODEL PROMPT --format json --keepalive 5m --verbose`
- `OLLAMA_HOST=127.0.0.1:11434`
- `OLLAMA_NO_CLOUD=1` for no-cloud local mode.
- `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_NUM_PARALLEL`,
  `OLLAMA_MAX_QUEUE`, and `OLLAMA_LOAD_TIMEOUT` for throughput and stability.
- API `format` supports `"json"` or a JSON schema object.
- API response includes `done_reason`, `prompt_eval_count`, `eval_count`,
  `total_duration`, `load_duration`, and token timing fields.

Avoid in Distill automation:

- `--experimental-websearch`, unless the user explicitly opted into web tools.
- `--experimental-yolo`.
- Unbounded `ollama run` calls without `num_predict` or an external timeout.

### LM Studio

Best default when the user prefers LM Studio's local model management or wants
OpenAI-compatible and Anthropic-compatible local endpoints.

Preferred server startup:

```text
lms server start --bind 127.0.0.1 --port 1234
```

Preferred API pattern:

```text
POST http://localhost:1234/v1/chat/completions
{
  "model": "<loaded-model-id>",
  "messages": [...],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "distill_result",
      "schema": { ... }
    }
  }
}
```

Useful flags and commands:

- `lms server status`
- `lms server start --bind 127.0.0.1 --port 1234`
- `lms ps`
- `lms load <model path>`
- `lms server stop`

Avoid in Distill automation:

- `lms server start --bind 0.0.0.0`, unless the user explicitly requests LAN
  exposure.
- `--cors`, unless a browser app integration explicitly needs it.
- Hardcoded model names. List or probe loaded models first.

## Included plan-quota CLI routes

### Codex CLI

Best default for bounded high-judgment planning, critique, and code-aware
research tasks when the user has an included Codex plan session and no API-key
route is active.

Preflight:

- `codex --version`
- `codex exec --help`
- Scan `~/.codex/config.toml` for API-key routing fields.
- Remove `OPENAI_API_KEY` and `CODEX_API_KEY` from the subprocess environment.
- If auth cannot be classified as an included plan session, block in
  `no-metered`.

Read-only prompt command:

```text
codex exec --sandbox read-only --ephemeral --json \
  --output-schema result.schema.json \
  --output-last-message result.txt -
```

Scratch-write command, only after eval:

```text
codex exec --sandbox workspace-write --ephemeral --json \
  --cd <scratch-workspace> \
  --output-schema result.schema.json \
  --output-last-message result.txt -
```

Useful flags:

- `--sandbox read-only|workspace-write|danger-full-access`
- `--json` for JSONL events.
- `--output-schema <file>` for final response shape.
- `--output-last-message <file>` for stable result capture.
- `--ephemeral` to avoid session persistence.
- `--ignore-rules` in controlled automation when Distill supplies its own
  policy.
- `--ignore-user-config` only when Distill supplies a known-good config profile.
- `--oss --local-provider ollama|lmstudio`, observed locally in 0.140.0, should
  be treated as experimental until adapter doctor validates it.

Native usage capture:

- `codex exec --json` emits `turn.completed` events with a `usage` object.
- `distill.doctor.adapter_native_usage.codex_jsonl_native_usage()` parses that
  JSONL and converts the summed token fields into `adapter-native-usage.v1`.
- `distill.doctor.adapter_capture.write_codex_captured_result()` writes that
  native usage file and the validated `adapter-result.v1` manifest from
  captured stdout JSONL plus `result.txt`.
- The workload runner can invoke this writer through a capture hook after a
  successful process exit, but the helper does not make Codex route-eligible.
  Auth, support, and eval gates still apply.

Avoid in Distill automation:

- `--sandbox danger-full-access`.
- `--dangerously-bypass-approvals-and-sandbox`.
- `--add-dir <library>`, because additional directories are writable. Stage
  sources into scratch instead.

### Claude Code

Best default for bounded high-judgment planning and review when the user has
subscription quota available. It should not be scheduled for fan-out until
`claude auth status --json` and a smoke call prove quota is available.

Preflight:

- `claude --version`
- `claude auth status --json`
- `claude -p --help`
- Remove `ANTHROPIC_API_KEY` from the subprocess environment for subscription
  routing.
- If `ANTHROPIC_API_KEY` is present or auth status indicates console/API usage,
  classify the route as metered.

Tool-less structured command:

```text
claude -p "<prompt>" \
  --output-format json \
  --json-schema '<schema-json>' \
  --tools "" \
  --max-turns 1 \
  --no-session-persistence
```

Read-only file-aware command, only for staged scratch sources:

```text
claude -p "<prompt>" \
  --output-format stream-json \
  --verbose \
  --tools "Read" \
  --add-dir <scratch-workspace> \
  --permission-mode default \
  --max-turns 3 \
  --no-session-persistence
```

Useful flags:

- `-p`, `--print` for non-interactive mode.
- `--output-format text|json|stream-json`.
- `--json-schema <schema>` for validated structured output.
- `--tools ""` to disable tools, or `--tools "Read"` for read-only staged
  sources.
- `--disallowedTools` for deny rules.
- `--permission-mode plan|default|acceptEdits|auto|dontAsk|bypassPermissions`.
- `--max-turns <n>` for loop bounds.
- `--no-session-persistence`.
- `--worktree [name]` for isolated code-editing sessions, not first-wave
  Distill profile analysis.

Avoid in no-metered subscription routing:

- `--bare` on the local 2.1.173 binary. Local help says bare mode uses
  `ANTHROPIC_API_KEY` or `apiKeyHelper` auth and never reads OAuth/keychain, so
  it is not a subscription-quota route.
- `--dangerously-skip-permissions`.
- `--allow-dangerously-skip-permissions`.
- `--permission-mode bypassPermissions`.

Quota behavior to record:

- A 429 weekly-limit response with zero tokens and zero cost is a clean quota
  stop, not a model-quality failure.

Native usage capture:

- `claude -p --output-format json` emits a result object with `usage` metadata,
  and `stream-json` can carry usage on message objects.
- `distill.doctor.adapter_native_usage.claude_json_native_usage()` parses those
  usage objects into `adapter-native-usage.v1`.
- `distill.doctor.adapter_capture.write_claude_captured_result()` writes
  `native-usage.json`, `result.txt`, and a validated `adapter-result.v1`
  manifest from captured Claude JSON stdout.
- The helper does not make Claude route-eligible. Auth, support, and eval gates
  still apply.

### Grok Build

Best default for bounded high-judgment planning, cross-topic synthesis planning,
and app integration when cached-token or subscription auth is available.

Preflight:

- `grok --version`
- `grok inspect --json`
- `grok models`
- Scan `~/.grok/config.toml` for `api_key` or `env_key`.
- Remove `XAI_API_KEY` from the subprocess environment for plan-quota routing.
- If ACP reports `xai.api_key` instead of `cached_token`, classify as metered.

Headless JSON command:

```text
grok --no-auto-update \
  -p "<prompt>" \
  --output-format json \
  --cwd <scratch-workspace> \
  --disable-web-search \
  --no-subagents \
  --no-memory \
  --max-turns 1
```

Durable app integration:

```text
grok --no-auto-update agent stdio
```

Useful flags:

- `-p`, `--single <prompt>`.
- `--prompt-file <path>` for large prompts.
- `--output-format plain|json|streaming-json`.
- `--cwd <path>`.
- `--model <model>`.
- `--session-id`, `--resume`, `--continue` for controlled session reuse.
- `--max-turns <n>`, observed locally in 0.2.50.
- `--disable-web-search`, observed locally in 0.2.50.
- `--no-subagents`, observed locally in 0.2.50.
- `--no-memory`, observed locally in 0.2.50.
- `--permission-mode plan|default|acceptEdits|auto|dontAsk|bypassPermissions`.
- `--tools`, `--disallowed-tools`, `--allow`, and `--deny` for tool policy,
  observed locally in 0.2.50.

Avoid in Distill automation:

- `--always-approve`, except inside an isolated scratch workspace after adapter
  eval.
- `--permission-mode bypassPermissions`.
- Web search for no-metered corpus analysis unless explicitly requested.

### Gemini CLI

Best default for bounded read-only planning only after an included-plan session,
machine-readable output, usage capture, and eval evidence are proven. Local
0.46.0 help shows headless `--prompt`, JSON output, and `--approval-mode plan`.

Preflight:

- `gemini --version`
- `gemini --help`
- Scan `~/.gemini/settings.json` for API-key routing fields.
- Remove `GEMINI_API_KEY` and `GOOGLE_API_KEY` from the subprocess
  environment for plan-quota routing.
- If auth cannot be classified as an included plan session, block in
  `no-metered`.

Headless JSON command shape:

```text
gemini \
  --approval-mode plan \
  --output-format json \
  --prompt ""
```

Distill passes the staged prompt file on stdin through the scratch workload
runner. Local Gemini help says stdin is appended to `--prompt`, so the template
keeps `--prompt` present while avoiding shell piping.

Current blockers:

- The local CLI has JSON output, but no observed native `--output-schema`
  enforcement in 0.46.0 help.
- Included-plan auth proof and eval graduation are still pending.

Useful flags observed locally in 0.46.0:

- `-p`, `--prompt` for non-interactive mode.
- `--output-format text|json|stream-json`.
- `--approval-mode default|auto_edit|yolo|plan`.
- `--sandbox` for sandboxing, not yet validated for Distill workloads.
- `--allowed-mcp-server-names` to constrain MCP access.
- `--include-directories` for extra context directories, avoided until eval.

Avoid in Distill automation:

- `--yolo`.
- `--approval-mode yolo`.
- `--raw-output`, unless a wrapper explicitly accepts and sanitizes the risk.
- `--skip-trust`, unless Distill supplies an isolated scratch workspace and
  matching policy.
- `--include-directories <library>` because additional directories increase
  the readable surface. Stage sources into scratch instead.

### Antigravity

Antigravity is currently the weakest included-plan CLI candidate for Distill
automation. Local 1.107.0 help exposes `antigravity chat --mode ask -`, but it
does not expose headless JSON output, schema enforcement, or native usage
signals in the local help surface.

Preflight:

- `antigravity --version`
- `antigravity --help`
- `antigravity chat --help`
- Scan `~/.antigravity/settings.json` for API-key routing fields.
- Remove `GEMINI_API_KEY` and `GOOGLE_API_KEY` from the subprocess
  environment for plan-quota routing.
- If auth cannot be classified as an included plan session, block in
  `no-metered`.

Blocked chat command shape:

```text
antigravity chat \
  --mode ask \
  -
```

Current blockers:

- The local chat command lacks observed headless JSON output.
- The local CLI has no observed native `--output-schema` enforcement in 1.107.0
  help.
- Included-plan auth proof and eval graduation are still pending.

Useful flags observed locally in 1.107.0:

- `chat [prompt]` for a chat session in the current working directory.
- `--mode ask|edit|agent|<custom>` for mode selection.
- `--add-file <path>` for context files, avoided until eval.
- Stdin can be provided by appending `-`.

Avoid in Distill automation:

- `--mode edit` and `--mode agent` until scratch-write eval exists.
- `--add-file <library>` because additional files increase the readable
  surface. Stage sources into scratch instead.
- Top-level editor window flags such as `--reuse-window`, `--new-window`, and
  `--wait` for batch workloads.

## Credit-metered CLI candidates

### GitHub Copilot CLI

Copilot CLI is supportable as an external worker, but not as a default
no-metered route. GitHub documents Copilot usage through plans, AI credits, and
usage limits, so Distill should classify it as credit-metered unless adapter
doctor can prove a no-incremental-cost entitlement.

Preflight:

- `copilot --version`
- `copilot --help`
- Inspect local Copilot config for auth and entitlement metadata when a
  documented machine-readable command exists.
- If entitlement, AI-credit status, or usage accounting is unknown, block in
  `no-metered` and allow only under `paid-ok` or a future explicit
  plan-credit policy.

Adapter shape:

- Prefer plan or review modes for read-only planning and critique.
- Require either structured output or a scratch result manifest before the
  route can feed Distill automation.
- Record AI-credit usage or the nearest native usage signal on the ledger.
- Do not let Copilot write directly to `library/`.

## Cross-route eval

Every candidate route should run the same fixture package and write the same
manifest shape. Fixture packages use this checked input contract:

```yaml
schema_version: adapter-workload.v1
workload: profile-enrichment|corpus-qa|candidate-classification|synthesis-planning
command_class: read-only|scratch-write
prompt_path: prompt.md
source_paths:
  - sources/input.md
output_schema_path: schemas/result.json|null
result_manifest_path: adapter-result.json
allowed_write_paths:
  - result.json
cost_mode: no-metered|auto|paid-ok
max_seconds: integer
output_limit: integer
metadata: object
```

The checked parser lives in `distill.doctor.adapter_workload`. It rejects
absolute paths, drive-letter paths, empty paths, `.` segments, `..` segments,
empty source sets, non-positive limits, unknown fields, and read-only workloads
that declare write paths.
The workload runner can pass a staged scratch file as stdin without shell
piping, and rejects stdin paths outside scratch.

```yaml
schema_version: adapter-result.v1
adapter: codex|claude|grok|ollama|lmstudio
adapter_version: string
auth_class: local|included-plan|metered-api|unknown
command_class: read-only|scratch-write
model: string
prompt_hash: string
source_hash: string
elapsed_ms: integer
usage:
  input_tokens: integer|null
  output_tokens: integer|null
  native: object
stop_reason: string
quota_stop:
  reached: boolean
  reason: string
  retry_after_seconds: integer|null
  provider_code: string
  native: object
files_read:
  - sources/input.md
files_written:
  - result.json
output: object|string
policy:
  cost_mode: no-metered|auto|paid-ok
  blocked_api_key_env: [string]
  metered_allowed: boolean
```

The checked parser lives in `distill.doctor.adapter_manifest`. It rejects
unknown fields, unsafe relative paths, missing usage signals, unknown adapters,
and `no-metered` results that report metered auth, API-key blockers, or metered
usage allowance. If `stop_reason` is `quota`, `rate_limit`, or `rate-limit`,
the manifest must include `quota_stop.reached=true` with a reason. The same
module also provides scratch before/after snapshot checks so a runner can
reject missing declared files or unexpected new files without treating
pre-staged source files as adapter writes.

```yaml
schema_version: adapter-native-usage.v1
adapter: codex|claude|grok|gemini-cli|antigravity|copilot|ollama|lmstudio
source: cli-json|usage-file|stdout-json|stderr-json|wrapper
usage:
  input_tokens: integer|null
  output_tokens: integer|null
  native: object
model: string
request_id: string
stop_reason: string
metadata: object
```

The checked parser lives in `distill.doctor.adapter_native_usage`. It rejects
unknown fields, unknown adapters, missing usage signals, absolute paths, and
scratch path escapes. `distill.doctor.adapter_result_writer` can consume the
record from scratch when writing the result manifest.
The `distill.doctor.adapter_runner` primitive runs exact argv arrays with shell
disabled inside scratch, strips known metered API-key environment variables,
enforces a timeout, loads the result manifest, and applies the scratch write
check. It is a boundary helper, not a route recommendation.
The adapter doctor also emits structured support-statement details. Treat
`no_metered_current=false` as a hard block even when the binary, auth markers,
and manifest contract look compatible.
After a manifest is verified, `distill.doctor.adapter_ledger` can convert it
into a `TokenUsage` row plus cost-log metadata. Included-plan rows are
zero-dollar accounting records, not proof that the adapter should be selected.
`distill.doctor.adapter_workload_runner` composes the workload package with the
scratch runner. It blocks result manifests that read outside the workload
package, write outside declared outputs, or return a different cost mode.
`distill.doctor.adapter_result_writer` writes validated `adapter-result.v1`
manifests from captured CLI output, workload package hashes, and explicit
native usage metadata or validated native usage files. It does not invent usage
data or make an adapter eligible.
`distill.doctor.adapter_capture` contains adapter-specific capture writers.
The Codex writer converts captured JSONL stdout plus `result.txt` into a
scratch native usage file and result manifest, and the workload runner can
invoke it through a post-process capture hook before manifest validation.
The Claude writer converts captured JSON stdout into a scratch native usage
file, `result.txt`, and result manifest through the same workload-runner hook.
The generic stdout writer saves captured stdout to `result.txt` and writes the
same result manifest from a validated native usage file, but it does not invent
usage signals.
`distill.doctor.adapter_commands` records blocked Codex, Claude, Grok, Gemini,
and Antigravity read-only argv templates. Command plans include staged prompt,
schema, result capture, native usage capture, and allowed scratch capture
metadata. Claude schema paths can be materialized into `--json-schema` argv
arguments from staged scratch JSON schema files, but templates stay blocked
until current support statement, auth proof, remaining adapter-specific native
usage capture where applicable, and eval evidence exist.

`distill eval` should judge local, plan-quota, and metered outputs head to head
on the same fixtures. The rubric is faithfulness to receipts, specificity,
citation use, synthesis quality, contradiction handling, actionability, and
concision. Promote the cheapest no-incremental-metered-cost route that clears
the quality bar. Do not promote a route merely because it is available.

## Sources

- OpenAI Codex CLI reference:
  <https://developers.openai.com/codex/cli/reference>
- OpenAI Codex non-interactive mode:
  <https://developers.openai.com/codex/noninteractive>
- OpenAI Codex sandboxing and approvals:
  <https://developers.openai.com/codex/concepts/sandboxing>
  and <https://developers.openai.com/codex/agent-approvals-security>
- Claude Code CLI reference:
  <https://code.claude.com/docs/en/cli-reference>
- Claude Code permissions and settings:
  <https://code.claude.com/docs/en/permissions>
  and <https://code.claude.com/docs/en/settings>
- xAI Grok Build headless scripting and enterprise auth:
  <https://docs.x.ai/build/cli/headless-scripting>
  and <https://docs.x.ai/build/enterprise>
- xAI Grok Build modes and commands:
  <https://docs.x.ai/build/modes-and-commands>
- Ollama generate API and structured outputs:
  <https://docs.ollama.com/api/generate>
  and <https://docs.ollama.com/capabilities/structured-outputs>
- LM Studio developer API and structured output:
  <https://lmstudio.ai/docs/developer>
  and <https://lmstudio.ai/docs/developer/openai-compat/structured-output>
- GitHub Copilot CLI:
  <https://docs.github.com/copilot/concepts/agents/about-copilot-cli>
  and <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference>
- GitHub Copilot usage limits:
  <https://docs.github.com/en/copilot/concepts/usage-limits>
