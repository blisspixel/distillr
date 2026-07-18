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
- Website discovery caps sitemap attempts and entries. PDF attachment ingest
  caps attachments, aggregate bytes, per-transfer time, and batch time. X
  syndication requests identity encoding and caps raw response bytes before
  JSON decoding.
- Local HTML, PDF, and browser work runs in isolated child processes with
  elapsed-time, memory, process-tree cleanup, output, and diagnostic-tail
  limits. Browser requests also use HTTPS, public-address checks, a per-page
  request budget, and a restricted resource-type set.
- Process launches resolve one absolute executable identity outside the current
  directory, use a trusted working directory, and remove Python injection
  variables and provider credentials from child environments. Python module
  launches use safe-path mode.
- CLI target classification rejects UNC and Windows device paths before any
  filesystem probe. Persistent budget fields reject negative and non-finite
  values before mutation and serialize with strict JSON.
- Local phase, provider, and cost histories serialize cooperating writers,
  isolate an interrupted final row before the next append, and reject
  non-finite JSON on write. Provider-history reads stream strict JSON with a
  1 MiB row ceiling and continue past malformed or invalid UTF-8 rows. Cost
  rows are `fsync`-flushed before profile receipt state advances.
- MCP file tools use workflow-specific namespaces and artifact classes rather
  than broad library-root readability. Reads are no-follow and bounded. OKF
  validation has aggregate tree-work ceilings.
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

## Handling

Security reports will be acknowledged within a week, triaged, and - if confirmed - patched in a point release with a CHANGELOG entry noting the fix (without disclosing the exploit detail until users have had a reasonable window to update).
