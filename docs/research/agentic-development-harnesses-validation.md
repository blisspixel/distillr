# Agentic development harness validation

Validation date: 2026-07-11

## Decision

Distill should remain a loopable research primitive and persistent evidence
layer. It should not become a scheduler, worker queue, or general agent
orchestrator. External harnesses should own triggers, leases, concurrency, and
backpressure. Distill should own source acquisition, receipts, semantic
analysis, verification, idempotent writes, cost policy, and machine-readable
results.

That boundary matches both the project thesis and the strongest evidence in
this review. Natural-language policy and model judgment are useful inside a
harness, but durable state, deterministic contracts, and independent
verification are what make repeated execution dependable.

## Validation corpus

The working corpus combined three analyzed papers, four technical videos, and
five X posts. A fourth paper was reviewed directly as an external evidence
check. The source mix deliberately included controlled evaluations,
practitioner designs, product demonstrations, and short claims that stress
partial-capture and rumor handling.

Primary research:

- [Natural-Language Agent Harnesses](https://arxiv.org/html/2603.25723)
  represents run policy as an editable document interpreted by a shared
  runtime. Its ablations favor explicit file-backed state and evidence
  artifacts, while extra candidate calls and aggressive compression do not
  reliably help.
- [Agentic Harness Engineering](https://arxiv.org/html/2604.25850) reports a
  Terminal-Bench 2 pass@1 improvement from 69.7 to 77.0 across ten harness
  iterations. Its useful mechanism is not self-editing alone. It is the
  combination of component, experience, and decision observability plus a
  read-only verifier on the next iteration.
- [Human-In-The-Loop Software Development Agents](https://arxiv.org/html/2506.11009)
  shows why one score or one model judge is insufficient. Functional tests are
  stronger but costly, model judgments vary, and human agreement is imperfect.
- [Training Long-Context, Multi-Turn Software Engineering Agents with
  Reinforcement Learning](https://arxiv.org/html/2508.03501) shows that
  trajectory-level environment feedback can materially improve multi-turn
  software engineering performance. It also reinforces the cost and noise of
  unreliable tests and long rollouts.

Practitioner evidence:

- The [OpenAI Codex multitasking demo](https://www.youtube.com/watch?v=9ohXlkbXiM4)
  demonstrates isolated work and parallel task management, but it is a product
  demonstration rather than a controlled reliability evaluation.
- The [OpenAI harness engineering talk](https://www.youtube.com/watch?v=am_oeAoUhew)
  and [Thoughtworks sensors talk](https://www.youtube.com/watch?v=uLWOLmeHOSE)
  support deterministic constraints, repository guidance, and feedback at
  system boundaries.
- The [Temporal agent demo](https://www.youtube.com/watch?v=GEXllEH2XiQ)
  demonstrates durable workflow state and retries. It supports using an
  external workflow engine, not adding a scheduler to Distill.
- X was valuable for first-hand implementation notes and counterexamples, but
  it also produced the clearest fidelity failures. Preview-only articles,
  nested quoted notes, mutable engagement counts, and context-free benchmark
  numbers must not be treated as complete or independently corroborated
  evidence.

## What the dogfood run established

### Product architecture

The README and roadmap direction is coherent:

- Plain files are a strong handoff and recovery format. They preserve state
  across model calls, agent sessions, and tool vendors.
- Deterministic code should own identities, schemas, cost refusal, write scope,
  retry bounds, and verifier aggregation.
- Models should own source fit, novelty, faithfulness, contradiction
  interpretation, and synthesis planning.
- The local-first promise needs an eval gate. Local topology proves no metered
  cost, but it does not prove acceptable semantic quality.
- Plan-quota CLIs belong behind adapter preflight and evaluation. Installed
  binaries and subscription credentials are not proof of no incremental cost.

### Local execution

`qwen2.5:14b` through Ollama was practical on the test workstation. Short and
long video analysis generally completed in tens of seconds, and the full
two-pass mixed-source synthesis completed in several minutes with zero paid
spend. A 27B model partially offloaded to CPU and did not complete a useful
first response in the bounded trial. Model size alone was therefore a poor
route-selection rule on this hardware.

The 14B model was adequate for ingestion QA but did not clear a synthesis
quality bar. It over-weighted promotional video claims, under-used measured
paper results, and called weak or shared provenance independent
corroboration. The generated synthesis is retained as an eval artifact, not as
the authoritative research conclusion.

The final command ledger contains 17 nonempty runs and 40 model calls with
128,056 input tokens, 27,760 output tokens, and `$0.00` actual paid spend.
Provider telemetry, which also includes calls made before command-ledger
coverage was repaired, records 162,299 local tokens over 864.5 inference
seconds. The final audit classifies 7 of 12 source insights as verified clean,
1 as flagged, and 4 as unverified because no claim was checked. It does not
present zero coverage as a pass.

### Failures found by live replay

The run exposed defects that isolated unit tests had not made obvious:

- Ollama contention looked like a hang and could disrupt another resident
  model.
- Several no-metered paths reached cloud preflight or clients too late.
- Direct source replay repeated model work and ledger writes.
- Older X receipts could be incomplete or pair preview metadata with
  overconfident analysis.
- Verification sidecars with zero checked claims looked clean rather than
  unverified.
- Transcript-only numeric verification falsely flagged a video year that was
  present in persisted metadata.
- Local runs displayed and recorded cloud-dollar estimates.
- Filesystem-backed direct-ingest topics existed but inventory and audit
  reported an empty or single-source library.
- Budget exhaustion could be caught as an item-level failure and allow later
  model calls.
- Windows adapter and recurring-profile command rendering was not safe or
  readable for all shell metacharacters.

The validation change set addresses these failures with bounded contention
waiting, structured retryable busy results, earlier cost-policy gates,
idempotent direct replay plus explicit `--force`, semantic X hashes, partial
capture labels, verification coverage states, metadata-backed video evidence,
route-aware estimates, filesystem-aware read inventory, terminal budget
propagation, and platform-aware command rendering.

## Product plan

### Before 1.0

1. Keep the current stability focus. Freeze and test action, result, artifact,
   and error contracts before adding orchestration surface.
2. Add the mixed paper, video, and X corpus from this validation as a frozen
   eval fixture. Score source fidelity, claim support, source diversity,
   contradiction handling, partial-source caution, and synthesis usefulness.
3. Make synthesis evidence-aware. Each promoted claim should retain source
   identity, source type, independence, verification coverage, and evidence
   strength. Several claims copied through one post do not become several
   independent sources.
4. Finish profile semantics. Use the goal file for model-judged source fit and
   novelty, and support an exact mixed-source manifest that can be previewed,
   approved, and replayed without command choreography.
5. Add word and numeral equivalence to the deterministic numeric verifier, with
   conservative tests for amounts such as "over a thousand" and `$1000`.

### Next loop-ready layer

1. Standardize a command result contract with `run_id`, `action_id`,
   idempotency identity, prerequisites, write scope, selected route, cost,
   retryability, verifier result, artifact paths, terminal state, and approval
   class.
2. Add a campaign budget envelope above per-command limits. It should reserve
   or atomically debit one allowance across discovery, ingestion, synthesis,
   and evaluation processes.
3. Persist append-only phase and item events so interrupted work can resume at
   the last accepted artifact rather than repeat a whole command.
4. Evaluate the full execution surface, not only the model. Rows should include
   provider, model, adapter or harness version, prompt version, tool schema,
   route class, and verifier version.
5. Optimize for cost per accepted verified artifact. Attempts, tokens, and raw
   task throughput are diagnostic metrics, not the success metric.

### Explicitly outside Distill

- Worker scheduling, leases, queue fairness, and dependency execution
- Long-lived orchestration services
- Automatic use of ambiguous plan quota
- Unbounded best-of-N or critic loops
- A self-declared model `done` state without receipt-backed verification

External tools such as Temporal, CI, cron, Codex, Claude Code, or another
agent harness can own those loops. Distill should give them convergent commands,
structured retry signals, bounded spend, durable artifacts, and deterministic
acceptance checks.

## Repository quality result

The completed change set passes the repository release gates:

- 4,128 tests passed, 1 skipped, and 8 explicitly deselected.
- Branch coverage is 95.02%, above the enforced 95% floor.
- Ruff lint and format, Pyright, import contracts, public contract snapshots,
  Bandit, dependency audit, package build, and wheel web-asset checks pass.
- Live exact replay for video, paper, and X exits without artifact or ledger
  changes. Raw-only X replay also avoids repeat transcription.
- A forced local video run and two-pass synthesis both display and record a
  zero-dollar estimate, and no-metered doctor checks skip live cloud validation.

## Acceptance criteria for future dogfood runs

A validation campaign is successful only when:

- the exact source manifest is replayable;
- unchanged reruns are write-free and ledger-free;
- every model or transcription call is attributed to a route and cost class;
- ambiguous billing fails before a provider call;
- busy local capacity returns a structured nonterminal retry result;
- zero verification coverage is labeled unverified;
- partial receipts constrain the analysis prompt and output;
- synthesis can trace important claims to independent receipts;
- the paid total stays inside the campaign ceiling; and
- lint, typing, security, contract, build, and coverage gates pass.
