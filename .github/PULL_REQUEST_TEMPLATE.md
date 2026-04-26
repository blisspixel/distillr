<!--
Thanks for the contribution. A short description here plus the checklist below
is usually enough. See `docs/CONTRIBUTING.md` for the full guide.
-->

## What this PR does

<!-- One or two sentences. If it's a bug fix, link the issue. -->

Closes #<!-- issue number, if any -->

## Why

<!-- Context the reviewer needs to understand the change. What's the underlying problem? -->

## How it was tested

<!--
Brief description of how you verified the change. A new test? Manual CLI run?
Integration test against real APIs? Be honest about what you did and didn't test.
-->

## Checklist

- [ ] I've run `pytest -q` locally and all tests pass
- [ ] I've run `ruff check .` and `ruff format --check .` (or relied on pre-commit)
- [ ] I've run `bandit -r distill/ --severity-level medium` if the change touches security-sensitive code (subprocess, URL handling, secrets, MCP surface)
- [ ] If I added a new user-facing command or flag, `README.md` reflects it
- [ ] If I changed prompt templates or model routing, `docs/CHANGELOG.md` notes the behavior change
- [ ] If I added a new dependency, it's justified in the PR description

## Notes for the reviewer

<!-- Anything they should pay special attention to. Tradeoffs. Open questions. -->
