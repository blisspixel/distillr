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
manifest shape:

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
files_written:
  - path: result.json
output: object|string
policy:
  cost_mode: no-metered|auto|paid-ok
  blocked_api_key_env: [string]
  metered_allowed: boolean
```

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
