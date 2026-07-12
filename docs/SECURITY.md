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

## Handling

Security reports will be acknowledged within a week, triaged, and - if confirmed - patched in a point release with a CHANGELOG entry noting the fix (without disclosing the exploit detail until users have had a reasonable window to update).
