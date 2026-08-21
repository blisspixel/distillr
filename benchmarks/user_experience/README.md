# User-experience evidence

This manual release-evidence harness measures costs that warm corpus operations
do not cover:

- one clean environment creation and full install from the locally built wheel;
- dependency resolution from the public PyPI Simple API with the uv cache disabled;
- wheel, source-distribution, installed-environment, and dependency counts;
- 20 fresh-process `distill --version` and `distill --help` samples;
- 20 portable bundle and OKF exports over a fixed 1,000-source corpus;
- package uninstall after the command and export samples complete.

The install is the only phase allowed to use the public network. Measured CLI
and export processes run from a scratch working directory with credential-like
environment variables removed, no-metered cost mode, preflight and update checks
disabled, and a disposable generated corpus. The harness verifies stable
normalized output identities plus unchanged source and authoritative corpus
digests. Timing remains advisory.

Build artifacts first, then run locally with reduced iterations for a smoke:

```bash
uv build
uv run --no-sync python -m benchmarks.user_experience run \
  --wheel dist/distillr-*.whl \
  --sdist dist/distillr-*.tar.gz \
  --iterations 1 --warmups 0 --export-scale 20 \
  --output user-experience.json
```

Canonical receipts use 20 iterations, one warmup, and export scale 1,000. The
manual GitHub workflow is the supported canonical entry point.
