# Live reference-journey evidence

This harness collects the 1.0 release journeys that intentionally include live
network acquisition and model execution:

- 20 current arXiv papers
- a 50-video watch catch-up
- a five-page exact-URL site batch

These results are release evidence. They are not ordinary pull-request gates or
performance objectives.

The checked-in campaign is local-only. It requires an exact installed Ollama
model on a loopback endpoint, strips credentials, sets `DISTILL_COST_MODE` to
`no-metered`, applies zero-dollar workflow budgets, and rejects every metered or
unknown-cost ledger row. It will not pull a missing model. Paid external spend
for this campaign is structurally capped at `$0.00`.

Run preflight first:

```console
uv run python -m benchmarks.live_journey preflight \
  --manifest benchmarks/live_journey/campaign-local-0.19.68.json \
  --library .release-evidence/live-library
```

Persist each long journey independently:

```console
uv run python -m benchmarks.live_journey run \
  --manifest benchmarks/live_journey/campaign-local-0.19.68.json \
  --library .release-evidence/live-library \
  --distill .venv/Scripts/distill.exe \
  --journey papers-20 \
  --output .release-evidence/papers-20.json
```

Use `videos-50` and `site-batch-5` for the other two receipts. On POSIX hosts,
the executable is normally `.venv/bin/distill`.

Bundle only after all three receipts exist:

```console
uv run python -m benchmarks.live_journey validate \
  --manifest benchmarks/live_journey/campaign-local-0.19.68.json \
  --receipt .release-evidence/papers-20.json \
  --receipt .release-evidence/videos-50.json \
  --receipt .release-evidence/site-batch-5.json \
  --output-dir .release-evidence/bundle \
  --repository blisspixel/distillr \
  --commit-sha <exact-lowercase-commit-sha>
```

The validator requires exact item counts, complete run-ID correlation across
phase, provider, cost, and command logs, first and final structurally valid
verification timing, a 100 percent authoritative-source no-op replay rate, and
zero paid or unknown-cost calls. When a verification sidecar contains a content
binding, that binding must match. Receipts store hashes and counts, not command
stdout, stderr, source text, credentials, or model responses.
