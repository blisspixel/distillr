# Agentic balance: where distill uses a rule vs lets the model decide

> Status: design charter. Refines an earlier `AGENTIC_BALANCE` draft (Nick, 2026-06 deep-research sweep) into an in-repo, sourced decision framework. It grounds invariant #6 ("LLM proposes, Python decides") in primary sources and states the criterion distill uses to choose between deterministic code and model-driven control flow. It is the guardrail the two agentic-vision RFCs ([`agentic-distill-master-plan.md`](agentic-distill-master-plan.md), [`agentic-deep-synthesis.md`](agentic-deep-synthesis.md)) run inside.

## The axis

Anthropic's [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) draws the line distill designs along. Two architectural categories, distinguished by *who owns control flow*:

- **Workflow** — "systems where LLMs and tools are orchestrated through predefined code paths." Deterministic; the developer codes the path.
- **Agent** — "systems where LLMs dynamically direct their own processes and tool usage, maintaining control over how they accomplish tasks." The model decides its own execution strategy.

And the criterion for choosing:

- Workflows "offer predictability and consistency for well-defined tasks."
- Agents "are the better option when flexibility and model-driven decision-making are needed at scale" — specifically "open-ended problems where it's difficult or impossible to predict the required number of steps, and where you can't hardcode a fixed path."

With a default: "find the simplest solution possible, and only increasing complexity when needed … add complexity *only* when it demonstrably improves outcomes."

## distill's position: agentic at the leaves, deterministic at the decisions

distill is, by deliberate design, **a workflow at its spine with agentic judgment at the leaves and deterministic decisions over those leaves.** The pipeline shape — capture → analyze → verify → synthesize → report — is a predefined code path. The model is invoked where judgment is irreducible (reading a source into structured insight, writing cross-source synthesis prose, ranking candidates against a goal). But every *decision* over the model's output — what to keep, how to merge, where the threshold sits, whether a claim is supported — is deterministic Python.

That is invariant #6 restated against the axis: **"LLM proposes, Python decides. Models emit rows and prose; structural decisions — merge, dedup, canonicalization, thresholds, verification — are deterministic code."** The "Building Effective Agents" framing is its citation: distill keeps the *control flow* in workflow territory and spends the model where flexibility genuinely can't be hardcoded.

| Surface | Rule or agent | Why it sits there |
|---|---|---|
| Discovery (goal-aware fanout across YouTube/arXiv/web, rerank for fit) | **Agent** | Open-ended; the step count and the right sources can't be predicted or hardcoded — exactly the case the source names. |
| Discovery *sizing / dedup / selection* (score-cliff, corpus-dedup) | **Rule** | A well-defined decision over the agentic output; determinism buys reproducibility. |
| Per-source analysis + cross-source synthesis (prose, insights) | **Agent** | Judgment over natural language; the model's core competence. |
| Verify gate, concept merge/normalize, cost estimation, audit | **Rule** | Structural decisions and ground-truth checks — invariant #6 + #8. |
| Completion ("is this answer good enough to enter the corpus?") | **Rule, by ground truth** | See below — never a self-declared flag. |

## The failure modes the sources name, and distill's guard against each

- **Brittle hardcoded logic.** [Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) names "hardcoding complex, brittle logic" as a fragility source, and points the other way: "as model capabilities improve, agentic design will trend towards letting intelligent models act intelligently, with progressively less human curation." *distill's guard:* the open-ended surfaces (discovery, analysis, synthesis) are left to the model rather than scripted; the determinism is reserved for the *decisions*, which are well-defined and benefit from it.
- **Self-declared "done."** [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) names the "marked complete without proper testing" failure — an agent overclaiming completion. *distill's guard:* invariant #8 — a generated answer becomes corpus only after a grounding check against its cited sources. The write-time verify hook and `distill audit` measure completion **by ground truth (receipts), not by the model's confidence.** `ask --save` refuses an answer with an unsupported load-bearing claim.
- **Gating the reasoning instead of the tools.** [NVIDIA, Agentic Autonomy Levels and Security](https://developer.nvidia.com/blog/agentic-autonomy-levels-and-security/): "the risk lies mostly in the tools or plugins available" — gate the irreversible actions, not the thinking. *distill's guard:* MCP read-only mode plus per-call spend caps plus the ingest-domain allowlist gate the *write / spend / ingest* tools; the read and reasoning surface stays fully open. The keep-list is irreversibility, not intelligence.
- **Over-agentifying when a fixed path fits.** [HuggingFace smolagents](https://huggingface.co/docs/smolagents/en/conceptual_guides/intro_agents) is the counterweight — regularize *toward* a deterministic path when one fits. *distill's guard:* the workflow spine is the default; agentic behavior is added only at the leaves where it demonstrably earns its place, matching "add complexity only when it demonstrably improves outcomes."

## How this constrains the agentic-vision RFCs

[`agentic-distill-master-plan.md`](agentic-distill-master-plan.md) and [`agentic-deep-synthesis.md`](agentic-deep-synthesis.md) push distill to be *more* model-driven (adaptive lenses, goal-driven discovery, a self-running deep-synthesis loop). This charter is the boundary they operate within: **make the open-ended surfaces more agentic where flexibility helps, but keep the decisions deterministic (invariant #6) and completion ground-truthed (invariant #8).** A more agentic synthesis loop is welcome; a synthesis loop that decides for itself that it is finished, without a receipt check, is not.

## The direction of travel, with a gate

The sources agree on the drift — "less structure, more model" as capability rises. distill is built to move that way *without rewrites*: the `distill/llm` router abstracts provider+model behind workload tags, so the rule/model ratio can shift per-workload over time. But the shift is gated, not assumed: a workload moves from rule-assisted to more model-driven (or from cloud to local) only when **`distill eval`** shows it clears the cost×quality bar on the frozen fixtures. Flexibility is added when it demonstrably improves outcomes — the source's own test — never on vibes.

## Sources

- Anthropic, [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) — the workflow-vs-agent axis and decision criterion (quotes above verified 2026-06-13).
- Anthropic, [Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — brittle-hardcoded-logic failure; the "less structure, more model" direction.
- Anthropic, [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) — completion by ground truth, not a self-declared flag.
- NVIDIA, [Agentic Autonomy Levels and Security](https://developer.nvidia.com/blog/agentic-autonomy-levels-and-security/) — gate the tools (irreversible actions), not the reasoning.
- HuggingFace, [smolagents — Introduction to Agents](https://huggingface.co/docs/smolagents/en/conceptual_guides/intro_agents) — regularize toward a deterministic path when one fits.
- Background on autonomy levels: DeepMind's Levels of AGI and the autonomy-level literature (see the 2026-06 deep-research claim set for the full, adversarially-verified citation list).
