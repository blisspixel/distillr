# Roadmap review, 2026-08-20

## Decision

The selected milestone was cross-platform performance evidence for the 1.0
stability gate. It came before new adapters, provider routes, MCP Tasks, or a
native-language experiment.

The immediate deliverable is a manual GitHub Actions matrix that runs the
existing canonical corpus-scale and frozen workflow-replay suites on Linux and
macOS, validates every receipt, and uploads raw evidence plus a provenance
manifest. Timings remain advisory. Correctness and integrity fail closed.

## Evidence reviewed

The repository started this review with clean local and remote `main` at
`5a980be2706f998f1898d1eaff6db678230e847c`, release and PyPI version 0.19.64,
no open issues or pull requests, and all ten protected CI contexts passing on
the head commit. Existing performance evidence already covers Windows at 100,
500, 1,000, and 10,000 generated insights plus the frozen workflow replay at
n=20. Linux and macOS receipts were the earliest incomplete dependency in the
documented path to 1.0.

The external sweep reinforced that priority:

- The Markdown wiki category kept growing. On 2026-08-20,
  [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) had 46,884
  stars, [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) had 16,598, and
  [AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian)
  had 11,070. Storage format and generic vault maintenance are crowded surfaces.
- The [Open Knowledge Format v0.2 specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
  continues to make provenance, trust, lifecycle, and attestation first-class.
  Distill's defensible work remains verified acquisition and durable evidence,
  not another Markdown editor.
- The official [MCP Python SDK Tasks example](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/stories/tasks/README.md)
  still says the extension is not implemented. MCP Tasks therefore remains
  vendor-blocked and cannot outrank an evidence gate Distill controls.
- Standard GitHub-hosted runners are free for public repositories according to
  the [GitHub-hosted runners reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
  [Workflow artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts)
  preserve stress-test output with run identity, which fits raw benchmark
  receipts without introducing provider spend.

## Why this is next

1. It closes the earliest unresolved dependency in the existing 1.0 plan.
2. It uses mature harnesses already checked against Windows evidence instead of
   adding a new product surface.
3. It costs no model or API spend and makes performance claims reproducible.
4. It separates fail-closed correctness evidence from noisy hosted-runner
   timing, so the project does not invent premature thresholds.
5. It creates the comparable history needed before any honest regression gate
   or native-language admission decision.

## Ordered execution

1. Land the manual Linux/macOS collection workflow and evidence-bundle
   validator with unit and workflow-structure tests.
2. Run it on the exact merged `main` commit. Inspect both manifests and raw
   receipts, then publish a dated cross-platform baseline document.
3. Accumulate at least five comparable runs per host class before proposing a
   relative plus absolute timing regression policy.
4. Add clean-install, wheel-size, cold-start, and export measurements to the
   same evidence family.
5. Run the live 20-paper, 50-video, and site-batch journeys as release evidence
   with provider, hardware, token, cost, verification, retry, resume, and
   corpus-digest metadata. Keep them outside ordinary pull-request CI.
6. Continue the residual type, boundary, accessibility, presentation, and
   freeze-time security work after the cross-platform baseline is published.

Only steps 1 and 2 are the immediate milestone. Steps 3 through 6 are ordered
follow-ons, not reasons to widen the current change.

## First-run finding

The first exact-commit run on 0.19.65 completed successfully on Linux and
macOS, but comparison of the raw receipts found different `search_hit` result
digests with identical inputs and result counts. Equal-score search results
inherited filesystem traversal order before the result limit. Publication was
therefore deferred while 0.19.66 added a portable path representation and
deterministic path tie-break.

The fixed-commit run
[`32431022291`](https://github.com/blisspixel/distillr/actions/runs/32431022291)
then passed on Linux and macOS. Both downloaded bundles independently passed
hash and receipt validation, and all 32 operation result counts and digests
matched across hosts. The raw bundles and findings are published in
[`../performance/cross-platform-0.19.66.md`](../performance/cross-platform-0.19.66.md).
The next dependency is at least five comparable runs per host class so public
runner variance is characterized before any timing threshold is proposed.
