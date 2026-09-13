# Roadmap review, 2026-09-13

## Decision

Ship the bounded `0.20.1` maintenance release first: prove Ollama local-only
execution before inference, update MCP compatibility, and coordinate arXiv
requests within each process. The review found an actual billing-proof gap,
and the maintainer requested current GitHub and PyPI releases. This qualifies
for the roadmap's billing and compatibility blocker exception.

Then correct evidence generations and preserve derived origin in `0.20.2`,
followed by the `0.20.3` research-desk evaluation baseline. The product dependency
order remains sound. These unshipped milestones move forward by one patch
number; maintenance does not claim their exit evidence.

This review combines repository inspection, three independent research tracks,
and a tested MCP and Agent Plugins compatibility update. Account-specific
agent-host installation trials and expert-calibrated semantic evaluation remain
outstanding. Session logistics live in the local `.agent/` work state.

## Repository evidence

Reviewed `README.md`, both roadmap files, the research-desk doctrine, evidence
handoff design, positioning, claim extraction and storage, evaluation fixtures,
and CI configuration at commit
`cd3cc6879846b3a051ca4b1ba9449f2c2d9715cb`, package version `0.20.0`.

- [`latest_claims()`](../../distill/claims/exports.py) selects the newest row
  per claim ID. Since claim IDs include claim text, that cannot retire an
  assertion removed or rewritten by a source refresh.
- The [claim pipeline](../../distill/claims/pipeline.py) appends nonempty
  extraction results and records parsed sources as completed. A successful
  empty extraction does not itself publish a generation that supersedes
  previously stored assertions.
- The [claim record](../../distill/claims/records.py) stores source and artifact
  identifiers but has no explicit generation or source-versus-derived origin
  fields. The accepted
  [P0 design](../design/evidence-anchors-and-claim-handoff.md#phase-p0-active-generations-and-provenance-correctness)
  already specifies the intended correction and legacy compatibility rules.
- [Current evaluation fixtures](../../distill/eval/fixtures.py) cover paper,
  video, site, and ask workloads. They are not yet a baseline for the full
  selection, synthesis, refresh, disagreement, and stopping episode described
  in the research-desk doctrine.
- [CI run 34417069818](https://github.com/blisspixel/distillr/actions/runs/34417069818)
  passed on the reviewed commit. The supported Linux Python 3.12 through 3.14
  matrix, macOS and Windows tests, and quality jobs passed. Python 3.15's
  advisory job passed source compilation and its dependency probe, but skipped
  the unit suite and CLI smoke; that is not full Python 3.15 support evidence.

These findings support the existing sequence. They do not establish that a
high coverage percentage proves research quality or that the known trust
defect has already been repaired.

## The next implementation boundary

### README assessment

The README explains the capture, analysis, verification, and synthesis flow,
cost modes, artifact ownership, and beta status clearly. Its explicit 1.0
evidence gaps are useful and should remain visible.

Two presentation improvements belong with the operator-evidence work. First,
show the complete first useful loop: preview, bounded ingest, inspect receipts,
audit, and ask. The current opening stops the no-metered example at preview
and then introduces paid ingestion. Second, place the optional editorial
consumer after the core research outcome, so a new research user sees what
the corpus provides before a separate writing workflow. These are onboarding
hypotheses to check in `0.20.4`, not evidence of a measured conversion problem.

The confirmed factual corrections include published Agent Plugins status,
broader competitor capabilities, and Ollama's ability to proxy cloud inference
through localhost. The generation/origin defect remains an explicit next
release gate; documentation edits do not resolve it.

### `0.20.2`: evidence that remains correct after refresh

The user-visible acceptance example should be concrete: ingest a source that
makes two assertions, revise it to one assertion, then revise it to none. Each
successful refresh must expose only the current complete generation, while
retaining historical records for inspection. A failed refresh must preserve
the preceding complete generation and report the failed attempt.

| Case | Required result |
|---|---|
| Assertion removed or rewritten | Prior assertion is historical and absent from the active view |
| Successful zero-claim extraction | Empty complete generation retires previous active assertions |
| Structurally parsed but invalid claim rows | Invalid or incomplete output cannot masquerade as a successful empty generation |
| Parse, provider, budget, or publication failure | No partial generation becomes current; previous complete evidence remains available |
| Crash between durable writes | Recovery selects one complete generation without duplicate active evidence |
| Source changes during extraction | Publication detects the digest mismatch and refuses stale completion |
| Same short ID across source families | Qualified source identity prevents cross-source retirement |
| Saved corpus answer re-ingested | Derived origin and cited artifacts survive; independent-root counts do not increase |
| Legacy rows without provenance | Remain readable with explicit unknown values; no inferred independence |
| Concept mention refresh | Equivalent retirement behavior is verified before the trust issue is closed |
| Synthesis and audit | Both consume the same active evidence view and expose unresolved provenance |
| Active generation is empty | Synthesis cannot resurrect removed evidence by falling back to older per-source syntheses |

Use the existing append-only and locking boundaries. Preserve claim IDs and
public read compatibility. Finish regression, migration, fault-injection,
schema, and full CI evidence before calling this release complete. An
additional provider, graph backend, or relation engine is unnecessary for this
correction.

### `0.20.3`: measure the research episode

Build a small expert-reviewed fixture pack with three kinds of field:

| Field type | What the fixture must test |
|---|---|
| Mature | Canonical sources, missing foundations, redundant summaries, useful reading order |
| Fast-moving | A frozen before/after evidence set, revisions, removed claims, material versus cosmetic change |
| Contested | Independent roots, derivative coverage, incompatible scopes, real disagreement, honest uncertainty |

For each episode, preserve the research question, source snapshots and digests,
expected evidence roles, reference findings, known traps, model and prompt
versions, actual outputs, and per-criterion verdicts. Include a held-out case
set so prompt iteration does not quietly become fixture memorization.

Run paired tracks with a fixed expert source set and end-to-end discovery.
That separates retrieval failures from synthesis failures. Include incomplete,
throttled, and exhausted discovery as different outcomes. Deterministic search
can produce candidates; source relevance and research sufficiency still need
judgment. Do not ban lexical retrieval merely because it is deterministic.

Python should validate identity, receipt resolution, schemas, currentness,
allowed actions, and budget limits. Calibrated model judges and expert review
should assess source fit, contribution, faithfulness, disagreement, useful
change, navigation, and stopping. Agent-authored fixture drafts do not become
expert-reviewed gold until a qualified reviewer has checked them.

Publish failures by criterion and case. Do not substitute source counts,
citation counts, prose length, or a single aggregate score for this evidence.
Record token use, wall time, retries, and cost alongside semantic outcomes.

## Current external evidence and its implications

Sources below were opened on September 13, 2026. Their publication dates and
scope matter: a current retrieval date does not make an older study new.

| Primary source | Finding | Decision implication |
|---|---|---|
| [Google notebook source documentation](https://support.google.com/gemininotebook/answer/16215270?hl=en), living documentation | The product supports source search and Deep Research, including importing the report and selected sources | Correct the claim that notebook users must find every source manually; demonstrate Distill's file ownership, receipts, and refresh behavior directly |
| [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), January 9, 2026 | Research evaluation is task-dependent; code, model, and human graders have different roles, and model rubrics require human calibration | Supports the planned structural-versus-semantic split and expert review in `0.20.3`; it is engineering guidance, not a Distill benchmark result |
| [Do You Need a Frontier Model as a Citation Verifier?](https://arxiv.org/abs/2607.08700v1), July 9, 2026 | The abstract reports competitive cheaper judges and different directional error patterns despite similar aggregate performance | Evaluate false acceptance and false rejection on Distill fixtures before changing a verifier route; neither price nor one headline metric establishes judge suitability |
| [TaxoBench v5](https://arxiv.org/abs/2601.12369v5), revised August 6, 2026 | Separates end-to-end retrieval and organization from organization given experts' papers | Pair fixed-evidence and discovery episodes; its LLM-survey focus and reference-taxonomy assumptions limit transfer |
| [STALE](https://arxiv.org/html/2605.06527v1), May 7, 2026 | Tests whether agents apply updated evidence when resolving state, resisting stale premises, and adapting responses | Add current, stale-premise, and historical questions after the same update; personalized-memory scenarios do not validate a research corpus |
| [SAGE v2](https://arxiv.org/abs/2602.05975v2), February 6, 2026 | BM25 outperformed the tested LLM retrievers under keyword-oriented agent queries | Keep candidate retrieval distinct from semantic judgment; do not infer a universal retrieval winner |
| [W3C PROV-DM](https://www.w3.org/TR/prov-dm/), Recommendation April 30, 2013 | Distinguishes generation, invalidation, revision, quotation, and derivation | Preserve typed lifecycle and parent-artifact facts without adding RDF or claiming mechanically proven scientific independence |
| [Elicit Research Agent](https://elicit.com/blog/introducing-elicit-research-agent), August 4, 2026; [Khoj](https://github.com/khoj-ai/khoj) and [Obsidian Web Clipper](https://github.com/obsidianmd/obsidian-clipper), living repositories | Persistent research projects, broader source acquisition, and Markdown capture already overlap with Distill's surface | Replace categorical absence claims with a concrete repeated-research journey; vendor descriptions do not prove equivalent lineage or comparative quality |

These sources reinforce trust correction and evaluation as the near-term
priorities. They do not establish that Distill outperforms adjacent products,
that a new model is calibrated for Distill, or that an external worker is
included-plan rather than API-billed.

### Findings that changed the maintenance boundary

**Ollama billing proof.** The [current cloud guide](https://docs.ollama.com/cloud)
explicitly routes cloud models through localhost. At the reviewed commit,
`cost_policy.classify_provider()` uses endpoint topology alone, the router
accepts an explicit cloud model in no-metered mode, and `OllamaProvider`
classifies it local before seeing the model. An offline configuration probe
reproduced that admission. The earlier non-loopback tests do not cover this
native cloud proxy.

The [official API types](https://github.com/ollama/ollama/blob/main/api/types.go)
expose `remote_model` and `remote_host`; the
[API client](https://github.com/ollama/ollama/blob/main/api/client.go)
exposes the daemon's cloud status through `/api/status`. The
[local-only FAQ](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features)
requires disabling cloud and restarting the daemon. Setting an environment
variable only in Distill cannot reconfigure a running Ollama server.

Maintenance acceptance: prove the live daemon is cloud-disabled and the exact
requested model is local before prompt transmission; refuse unsupported,
missing, malformed, or remote proof in every cost mode; recheck on retries;
cover renamed aliases and changing metadata; never account cloud-backed work
as local zero-cost inference. Cloud-backed Ollama remains outside Distill's
implemented paid-provider contract. The runtime change is a release gate,
not something accomplished by correcting `AGENTS.md` alone.

**arXiv request coordination.** The [API terms](https://info.arxiv.org/help/api/tou.html)
require one request per three seconds and one connection across the operator's
machines. The reviewed implementation spaced only batch searches. Direct
search, ID fetch, and shared fetch retries lacked one coordinating boundary.
The maintenance fix must serialize and pace all canonical query-API callers,
including retries and redirects, with deterministic clock and concurrency
tests. A process-local gate cannot enforce an operator-wide limit across
other processes, machines, or generic RSS clients. Preserve that limitation
in operator guidance; no distributed scheduler is part of this patch.

## Research fan-out and loop

### MCP and Agent Plugins compatibility checkpoint

The additional September 13 request makes runtime interoperability part of
this review. The current
[MCP versioning page](https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning)
still identifies `2026-07-28` as current and permits compatible changes without
a new version identifier. Distill therefore needs both revision tracking and
runtime regression evidence.

The [SDK 2.2.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.2.0)
is dated September 7. The dependency floor and lockfile now select that tested
SDK line. Its Tasks gap remains explicit, so the upgrade does not justify
advertising Tasks or bypassing Distill's durable worker contracts.

New [stdio integration tests](../../tests/integration/test_mcp_stdio.py) launch
a real subprocess in an isolated temporary corpus with read-only and
no-metered policies. They cover automatic discovery, a direct `2026-07-28`
request before discovery, and the `2025-11-25` initialize handshake through
the SDK's legacy client mode. All three modes passed locally. The tests check
listing order, direct-response identity, tools/resources/templates/prompts, modern cache hints,
fresh reads after a corpus-state change, no Tasks advertisement, and refusal
of a forced synthesis write. This is protocol evidence, not an account-specific
trial in every agent host. Read responses must advertise zero TTL and private
scope; this is asserted separately because the SDK client does not cache
results. The child process reuses the test network and credential boundaries
and disables dotenv loading.

A fresh isolated genuine SDK 1.28.1 client also passed against the installed
release wheel's 2.2.0 server: protocol 2025-11-25, Distill 0.20.1, 27 sorted tools, 4 resources, 8 templates,
4 prompts, a resource read, and forced synthesis refusal without Tasks.
Historical and current receipts are distinguished in the
[adoption record](../design/mcp-2026-07-28-adoption.md).

The [Agent Plugins normative specification](https://agent-plugins.org/specification)
now marks 1.0.0 Published. The required manifest and optional fixed component
locations still permit Distill's skills-only package. A package conforming to
those rules does not establish that every client implements the same loading,
permissions, or MCP behavior.

The fetched [canonical manifest schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json)
matches the checked-in fixture byte for byte after newline normalization:
`0a4aad95ce337878ad38802ebf0daa3fde76abe3f65400c86bcbb1ec0b3ab883`.
Both corpus and editorial distribution validators passed, and their release
archives built. The generator was changed before regenerating its owned
README; generated files were not patched manually. Host installation trials
remain a separate operator evidence gate.

### Independent research and review results

Three independent tracks covered research quality and trust, product and
acquisition, and providers/interoperability/release evidence. They combined
current primary sources with source and test inspection. The quality track
also reproduced the retained-claim and invalid-empty cases without a provider;
the interoperability track reproduced localhost cloud-model admission and
ran the genuine legacy-client test. No comparative product benchmark or paid
semantic evaluation was performed.

The second pass addressed concrete gaps: invalid extraction versus empty
success, stale synthesis fallback, paired retrieval/synthesis evaluation,
direct-response identity, read-cache metadata, child-process test isolation,
Ollama billing proof, and request pacing. These findings changed acceptance
criteria and the maintenance patch, while preserving the product priority
order. Raw working notes remain outside canonical documentation.

The remaining evaluation gap includes judge calibration: current source and
output excerpts are limited to 6,000 and 8,000 characters. Episode fixtures
must expose incomplete evidence and test support or disqualifying claims
beyond those limits. Preserve both ordering verdicts and inspect disagreement;
swapping order mitigates bias but does not prove its elimination. The citation
study uses model-council labels reviewed by one human, with some evaluated
models also in the council; its results do not calibrate Distill.

Any paid experiment needs an enforcing shared reservation that includes
concurrent calls, retries, and maximum output liability. Independent worker
budgets cannot each reuse the entire global allowance. A session's available
tools and a portable skill do not themselves establish its billing treatment.

## Follow-on order

Keep operator, install, accessibility, performance, and live-journey evidence
in `0.20.4`; strict-boundary and freeze-time security closure in `0.20.5`; and
the compatibility exercise in `1.0.0rc1`. Do not move any gate to complete
without exact-commit evidence.

After stability, use the baseline to admit a bounded inquiry-map and
portfolio-selection improvement through existing preview surfaces. Follow
with meaningful-change briefs and selective refresh only when the fixtures
show a better research outcome. This preserves the roadmap's central promise:
help a researcher understand more with less redundant reading while keeping
uncertainty and evidence inspectable.

## Documentation corrections

- Replaced the unsupported manual-only notebook and ephemeral-only research
  comparisons in [positioning](../positioning.md).
- Removed the public roadmap's stale restriction of inserted blocker patches
  to `0.19.x`, since the active release line is already `0.20.x`.
- Inserted the requested maintenance release for confirmed billing and
  compatibility blockers, preserving the dependency order of unfinished
  product milestones.

## Validation

The frozen release candidate passed 7,339 tests with 95.29% branch coverage on
Linux/Python 3.12. Ruff lint and formatting, production Pyright with warnings
denied, all four import contracts, Bandit, and dependency auditing passed.
Public contracts and both generated skill distributions validated; wheel,
source, and skill archives built. An isolated wheel installation passed CLI,
bundled-skill, six runtime-asset, and editorial-default smoke checks. A manifest
comparison confirmed that all 1,039 project files matched the tested snapshot
before these validation receipts were added.

Exact-commit CI and the release-specific native-evaluation decision remain
publication gates. The installed native runner's cost ceiling limits launches
but permits in-flight overruns, so it cannot enforce the authorized hard
spending cap. No paid model calls were made. Native host installation and
semantic calibration remain unvalidated.
