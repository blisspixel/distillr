# Workflow replay

This repository-only harness replays Distill paper, video, site, synthesis,
numeric verify, profile preview/run, and report synthesis paths against frozen
receipts and a deterministic model stub. It is advisory evidence, not a public
product command.

It does not read a user library, does not call a live model, and fails closed if
a sample tries to open a public socket. Distill-owned wall time is recorded
separately from simulated provider wait (`--wait-ns`, default 0).

```console
uv run --no-sync python -m benchmarks.workflow_replay --iterations 5
```

Published Windows n=20 receipts live under `docs/performance/`. p95 is omitted
below 20 successful samples. Every recorded sample runs in a fresh child
process. Timing values never affect the exit code; an operation error or source
integrity failure returns nonzero.
