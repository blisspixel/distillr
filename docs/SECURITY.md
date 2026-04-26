# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in distill — particularly anything involving API key handling, file-path escapes, command injection, credential leakage via logs or cost artifacts, or the MCP server — please **do not open a public GitHub issue**.

Instead, reach out privately via the GitHub security advisory flow for this repo, or open an issue titled "Security — please contact me privately" with no details, and a maintainer will reach out.

## Scope

In scope for security reports:

- Credential leakage through logs, cost artifacts, or output files
- Path traversal or file-write escapes from user-controlled inputs (topic names, paper titles, website URLs)
- Command injection via subprocess calls (`yt-dlp`, `playwright`, `scribe`)
- MCP server authentication or tool-authorization issues
- Dependency vulnerabilities in pinned versions
- Prompt injection that causes distill to take actions outside its intended scope

Out of scope:

- Rate limiting on the user's own API keys — that's upstream (xAI, Google)
- Cost overruns from normal use — that's a budget issue, not a security issue (though budget-guardrail bugs that bypass user-set limits are in scope)
- Issues that require the attacker to already have write access to the user's library directory

## Handling

Security reports will be acknowledged within a week, triaged, and — if confirmed — patched in a point release with a CHANGELOG entry noting the fix (without disclosing the exploit detail until users have had a reasonable window to update).
