# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in distill - particularly anything involving API key handling, file-path escapes, command injection, credential leakage via logs or cost artifacts, or the MCP server - please **do not open a public GitHub issue**.

Instead, use the repo's [private GitHub security advisory
flow](https://github.com/blisspixel/distillr/security/advisories/new). If that
is unavailable, open an issue titled "Security - please contact me privately"
with no details, and a maintainer will reach out.

## Scope

In scope for security reports:

- Credential leakage through logs, cost artifacts, or output files
- Path traversal or file-write escapes from user-controlled inputs (topic names, paper titles, website URLs)
- Command injection via subprocess calls (`yt-dlp`, `playwright`, `scribe`)
- Server-side request forgery (SSRF): an attacker-influenced URL (site, feed, repo, paper, or one passed to an MCP write tool) reaching internal, loopback, link-local, or cloud-metadata addresses. Egress is meant to be confined to public hosts (`ingestors/net.py`), and URLs handed to yt-dlp are host-pinned to YouTube
- Resource exhaustion / denial of service from maliciously large or malformed untrusted responses (unbounded reads, parser crashes, catastrophic regex backtracking)
- MCP server authentication or tool-authorization issues
- Deferred worker queue escapes, claim-ownership bypasses, or acceptance of
  unexpected scratch writes
- Dependency vulnerabilities in pinned versions
- Prompt injection that causes distill to take actions outside its intended scope

Supply-chain posture:

- Runtime and development dependencies are pinned through the committed `uv.lock`; CI installs the locked environment with `uv sync --frozen`.
- `bandit`, `pip-audit`, import-linter, ruff, Pyright, build, and the coverage gate run in CI.
- GitHub Actions are pinned to full commit SHAs, including the PyPI publish action. Action and dependency bumps are reviewed manually.
- PyPI publishing uses OIDC trusted publishing with no stored package token.
  PyPI distributions carry PEP 740 provenance attestations, and each GitHub
  release includes a CycloneDX SBOM.

Out of scope:

- Rate limiting on the user's own API keys - that's upstream (xAI, Google)
- Cost overruns from normal use - that's a budget issue, not a security issue (though budget-guardrail bugs that bypass user-set limits are in scope)
- Issues that require the attacker to already have write access to the user's library directory

## Enforced runtime boundaries

Current source and integration paths apply several independent controls so one
malicious input cannot turn a narrow operation into broad host authority:

- The shared public-source opener accepts HTTPS, canonicalizes hostnames to one
  IDNA ASCII identity, rejects any DNS set containing a non-public address,
  pins the validated address for the connection, revalidates redirects, and
  carries one monotonic deadline through DNS, lock wait, connect, TLS, response
  headers, retry backoff, and caller body reads.
- Network diagnostics retain only the safe scheme, canonical host, and explicit
  port needed to identify a failing origin. User information, passwords, query
  strings, and fragments are omitted so bearer URLs do not become persistent
  log secrets.
- Source fetches keep the complete URL only at the request boundary. Website
  artifacts, prompts, attachment inventories, and run evidence retain a
  query-free public URL, while page ownership uses a domain-separated digest of
  the complete canonical request identity. This preserves distinct pages
  without copying URL capabilities into broader output channels.
- Website discovery caps sitemap attempts and entries. PDF attachment ingest
  caps attachments, aggregate bytes, per-transfer time, and batch time. X
  syndication requests identity encoding and caps raw response bytes before
  JSON decoding.
- Local HTML, PDF, and browser work runs in isolated child processes with
  elapsed-time, memory, process-tree cleanup, output, and diagnostic-tail
  limits. Browser requests also use HTTPS, public-address checks, a per-page
  request budget, and a restricted resource-type set.
- Process launches resolve one absolute executable identity outside the current
  directory and reuse that identity for execution. Children use a trusted
  working directory and environments stripped of Python and Node loader
  overrides, provider credentials, bearer tokens, passwords, and secrets.
  Python module launches use safe-path mode.
- Candidate adapter probes also bound stdout, stderr, elapsed time, process-tree
  memory, config bytes, auth JSON bytes, structural depth, and node count.
  Linked, multiply linked, oversized, malformed, or deeply nested adapter
  configuration is reported as blocked evidence rather than parsed recursively.
- No-metered local inference is topology-bound. Ollama and LM Studio count as
  local only at strict loopback HTTP(S) endpoints. Remote, deceptive, malformed,
  wildcard, and unsupported endpoint overrides fail closed before provider
  construction and are never recorded as local or zero-dollar model work.
- Local-provider endpoint URLs cannot contain credentials, query strings,
  fragments, control characters, or invalid ports. Provider inventories and
  Ollama contention metadata are streamed through byte, time, count, field, and
  identifier limits before they can affect routing or user-visible diagnostics.
- Preview snapshots are written through the serialized atomic artifact writer
  and require the supported schema before exact-set replay. Generated replay
  commands bind topic option values as one argument and decline values that
  cannot be represented portably.
- Media transcription copies a stable, single-link regular input into private
  scratch before local or cloud work. Local faster-whisper and configured
  Scribe execution use isolated process trees with elapsed-time, memory,
  output, and diagnostic limits; bounded structured results are required
  before the parent accepts success.
- CLI target classification rejects UNC and Windows device paths before any
  filesystem probe. Persistent budget fields reject negative and non-finite
  values before mutation and serialize with strict JSON.
- Local structured histories serialize cooperating writers, isolate an
  interrupted final row before the next append, refuse linked or special
  targets, and reject non-object or non-finite JSON before touching the file.
  Provider-history reads stream strict JSON with a 1 MiB row ceiling and
  continue past malformed or invalid UTF-8 rows. Cost, claim, mention, and
  completion-receipt rows are `fsync`-flushed before dependent state advances.
- Cost-ledger readers are no-follow and side-effect-free. Confined input is
  capped at 16 MiB, encoded rows at 1 MiB, and retained valid history at 10,000
  rows. Invalid monetary or timestamp evidence makes completeness-sensitive
  totals, calibration, warnings, and budget decisions unavailable instead of
  silently understating spend.
- Mutable library, watch, and per-channel state uses bounded strict-JSON reads
  and locked read-modify-write transactions. Corruption is rechecked under the
  writer lock and preserved in a non-colliding backup. Backup or persistence
  failure is explicit and cannot advance the in-memory state.
- MCP file tools use workflow-specific namespaces and artifact classes rather
  than broad library-root readability. Reads are no-follow and bounded. OKF
  validation has aggregate tree-work ceilings.
- MCP topic orientation reads only a bounded prefix of confined synthesis
  candidates and distinguishes absent, degraded, and unavailable evidence.
  Legacy wiki-link migration applies the same visible, bounded, no-follow file
  posture and returns a nonzero exit when any repair cannot be completed.
- The read-only web dashboard binds only to literal loopback hosts, rejects
  malformed or non-loopback Host headers, sanitizes rendered corpus Markdown,
  drops external images, and sends no-referrer and restrictive CSP headers.
  Executable JavaScript is served only from same-origin static assets; inline
  script, object embedding, and framing are refused.

Resource-boundary failures are explicit. User-facing commands return a refusal
or failed-item record, bounded child diagnostics retain only a small tail, and
no partial insight or worker result is accepted as success.

## Active host-worker boundary

`distill worker` accepts results from an already active external agent session.
Distill does not launch or sandbox that host process. The host must keep its own
approval and sandbox controls enabled.

The protocol limits what Distill accepts: one atomic claim, identity-bound task
and scratch directories, no-follow bounded reads, unchanged staged prompt and
metadata hashes, an exact workspace file set, one result path, bounded output,
an ownership token, immutable abandonment or release receipts, and a validated
submission receipt before replay. Provider admission, claim, submit, abandon,
and expired release share one cross-process transition lock. Submit rechecks
the exact active claim and workspace set immediately before receipt and result
publication, so revoked or replaced ownership cannot publish later. Duplicate
pending prompts converge on one task, and the queue has a fixed task ceiling.
Worker output still passes through the normal Distill verification and
corpus-write path. Queue files and receipts are not a public editing surface.

Supported examples pass the claim token through
`DISTILL_WORKER_CLAIM_TOKEN`, not a process argument. Keep it out of scripts,
logs, and shell history, expose it only to the submit or abandon process, and
clear it afterward.

Host billing is outside this security boundary. Results are labeled
`host-managed`, never proven no-metered, because the enclosing session may use
plan quota, credits, an API key, or another route Distill cannot observe.

## Trust model (operator summary)

Everything ingested (transcripts, pages, PDFs, tweets, READMEs, feeds) is
treated as **untrusted input**. Injection-resistance rules are threaded through
first- and second-hop prompts; the dashboard sanitizes rendered HTML; MCP file
reads are confined to explicit namespaces, artifact classes, and byte limits
(read-only mode available via `DISTILL_MCP_READ_ONLY`). Distill never bypasses
login walls, captchas, or anti-bot defenses. YouTube extraction depends on
yt-dlp and can churn with platform countermeasures; transient caption failures
retry with backoff, captionless videos fall back to the local-first Whisper
ladder, and remaining failures degrade with messages rather than corrupted
corpora.

Analysis output is LLM-generated and can err. Provenance fields exist so you
can check receipts, and Distill checks them itself: a write-time verify hook
grounds numeric claims in every insight against its source receipt before
commit (`--verify warn|strict|off`). Answers from `distill ask` only re-enter
the corpus if they pass that gate. The optional entailment tier
(`pip install distillr[entailment]`) extends prose claims with a local
cross-encoder. `distill audit` rolls verification coverage, prompt staleness,
synthesis freshness, duplicates, and coverage gaps into a free, deterministic
per-topic report. See [usage.md](usage.md#claim-verification-the-verify-hook)
and the [roadmap security section](../ROADMAP.md#security-posture).

## Release quality gate

Every release clears the same CI gate: a large automated suite at 95% **branch**
coverage, ruff + import-linter + pyright + bandit + pip-audit, pinned
dependencies via a committed `uv.lock`, SHA-pinned Actions including the PyPI
publish action, and PEP 740 build provenance on every PyPI release. Default
tests mock LLM and network boundaries; live integration tests are marked and
opt-in.

## Handling

Security reports will be acknowledged within a week, triaged, and - if confirmed - patched in a point release with a CHANGELOG entry noting the fix (without disclosing the exploit detail until users have had a reasonable window to update).
