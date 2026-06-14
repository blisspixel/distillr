# Model judgment vs brittle fallbacks: use what they have, degrade honestly

> Status: design charter + remediation plan. Sibling to [`agentic-balance.md`](agentic-balance.md), which draws the rule-vs-judgment line; this doc applies that line to one recurring violation — **deterministic keyword/regex heuristics standing in for a semantic judgment** — and plans the fix. Triggered by a June-2026 audit (Nick) that found the eval grader was not the only brittle proxy. Research → plan → fix; the fix is staged, not a hasty rip-out.

## The principle

Three rules, in order:

1. **A semantic judgment is a model's job.** "Is this video on-topic / practical / a credible leak?", "is this paper substantive?", "how good is this analysis?" — none of these have a regex answer. They are model calls (cloud or local). Encoding them as keyword lists is the "brittle proxy" failure mode named in [`agentic-balance.md`](agentic-balance.md).
2. **Use what the user has — never assume.** Do not assume a cloud key. Do not assume a local model. The router already abstracts provider+model behind workload tags and supports cloud (`xai`, `gemini`) *and* local (`ollama`, `lmstudio`, no key). Judgment routes to **whatever model is configured**: cloud preferred for quality, local when that is what they have. A feature asks the router "can I get a model for this workload?", not "is `XAI_API_KEY` set?".
3. **When there is genuinely no model, degrade honestly — don't fake it.** A brittle keyword score dressed up as a quality ranking is worse than an honest non-semantic order, because it hides the degradation. With no model available, fall back to a transparent, clearly-labeled deterministic order (recency / engagement metadata) and say so. Never present a keyword heuristic as if it were judgment.

This is invariant #6 ("LLM proposes, Python decides") read correctly: Python decides the *structural* things (dedup, thresholds, ordering arithmetic, output labels); the model makes the *semantic* call; and the no-model path is honest about being a downgrade.

## What June 2026 practice says

The graceful-degradation literature gives an explicit fallback ordering, and it puts rule-based heuristics dead last:

1. Alternative model, same capability tier
2. Different provider (… → **local model**)
3. Cached responses (labeled stale)
4. **Rule-based deterministic responses** — only after every model option is exhausted
5. Human escalation

Two findings matter here. First, **keyword/heuristic scoring as a fallback is a named anti-pattern** — acceptable only at tier 4, after cloud *and* local models are unavailable. Second, **every degraded response must be labeled**: "acknowledge unavailability, explain reduced capability, annotate uncertainty." Silent degradation "creates undetectable failure modes."

distill today does the inverse of both: the moment the *cloud* key is missing it drops straight to tier-4 keyword scoring, **skips the local-model tier entirely**, and **labels nothing**.

## The audit: where distill violates this

From the June-2026 sweep of `distill/`. Severity is "does it drive a user-visible decision," tempered by "primary path or fallback."

| Site | Semantic call faked with a rule | Primary or fallback | Severity |
|---|---|---|---|
| `pipeline/ranking.py` `rerank_videos:53` / `rerank_papers:477` | the gate `not config.xai_api_key` decides whether to use model judgment at all | **decides the path** | **HIGH** |
| `pipeline/ranking.py` `_skepticism_adjustment` / `_looks_like_rumor_query` (436) → `_auto_skeptical_mode` | "is this query/result a rumor or a prank?" by keyword list; **flips `skeptical` into the *primary* `_llm_rerank` prompt** | **leaks into primary** | **HIGH** |
| `pipeline/ranking.py` `_practicality_score` (276) | "how-to vs news" by booster/penalty keyword lists | heuristic rank (fallback) | MED |
| `pipeline/ranking.py` `_topicality_score` (302) | "is this on-topic?" by token overlap + ignore-list | heuristic rank (fallback) | MED |
| `pipeline/ranking.py` `_paper_depth_score` (600) | "is this paper substantive?" by substance-phrase list + length | heuristic rank (fallback) | MED |
| `prompts/lenses.py` `infer_lens` (64) | "which analytical lens does this goal want?" by keyword→lens cues | shapes primary prompt (model sees full goal too) | MED |
| `pipeline/analysis/reranker.py` `_score_chunk_for_category` (33) | "which chunks are relevant to this synthesis category?" by category keyword lists | local multi-pass | MED |
| `eval/scoring.py` (50) | "how good is this analysis?" by capitalization-regex + word count | **already remediated** — demoted to offline guardrail + noisy prior to the rubric judge | DONE |

The two HIGH rows are the real problem and share one root cause: **`ranking.py` asks `config.xai_api_key` instead of asking the router whether any model is available.** A user who set `provider=ollama` has an empty `xai_api_key`, so they get keyword scoring as their *primary* ranker while a perfectly good local judge sits idle. And the rumor/skeptical keyword trip-wire then reaches *into* the model path, telling the LLM to be skeptical based on whether the literal word "leak" (or, falsely, "analysis") appears in the query.

## The plan (staged)

**P1 — Route judgment to whatever model exists.** Replace the `not config.xai_api_key` gate in `rerank_videos` / `rerank_papers` (and any sibling) with a router capability check: "is a model available for the `rerank` workload?" (cloud key present, or a local provider configured and reachable). Cloud preferred; local used when that is what's configured. The keyword heuristic becomes tier-4 only. *Touches:* `ranking.py`, a small `RouterConfig.has_model_for(workload)` helper.

**P2 — Honest no-model degradation.** When P1's check finds no model at all, do not return keyword "quality" scores as if ranked. Return a transparent order (recency, then engagement metadata) wrapped with an explicit label — `selected_by="no-model:recency"` and a one-line console/notice "No model configured — showing newest first; add a cloud key or a local model for ranked results." Surface, don't hide, the downgrade.

**P3 — Kill the regex skeptical trip-wire.** Remove `_looks_like_rumor_query`-driven `_auto_skeptical_mode`. Skepticism is the model's read: the rerank/analysis prompt itself judges whether a source looks like an unverified leak and calibrates confidence. Keep only a genuinely structural guard if one is justified (e.g., the April-1 date check is a *date*, not a keyword — that may stay, clearly scoped). *Touches:* `commands/_learning.py`, the rerank prompt.

**P4 — Demote the remaining ranking heuristics + lens inference.** With P1 in place these only run at tier 4; document each as a brittle last-resort in its docstring (as `eval/scoring.py` now is), and let `infer_lens` defer to the model (the model already sees the full goal) rather than a keyword map deciding the lens.

**Sequencing.** P1+P2 together (they are one behavioral change: "model if available, honest order if not"). P3 independently. P4 last, mostly documentation + one deletion. Each stage gated by `distill eval` on the frozen fixtures — the same cost×quality bar the charter requires before changing a rule/model ratio.

## What this means for users (and for keys)

distill's judgments need a **model**, not specifically a *cloud* model. A user satisfies that with **either** a cloud key (`XAI_API_KEY` / `GEMINI_API_KEY`) **or** a configured local model (Ollama / LM Studio) — distill detects and uses whichever is present. No cloud key is *required*; `distill doctor` already reports local-inference readiness. The only hard requirement is "some model"; with none, features degrade to honest, labeled recency order rather than pretending. If a specific feature is ever found to genuinely need a capability only cloud models have, that gets called out explicitly rather than silently assumed.

## Sources

- [`agentic-balance.md`](agentic-balance.md) — the rule-vs-judgment criterion this applies; the "brittle proxy metrics" failure mode and the `eval/scoring.py` case study.
- Zylos Research, [Graceful Degradation Patterns in AI Agent Systems](https://zylos.ai/research/2026-02-20-graceful-degradation-ai-agent-systems/) (2026-02) — the fallback-chain ordering (model → provider → local → cached → rule-based), keyword heuristics as a tier-4 anti-pattern, and mandatory labeling of degraded output.
- Anthropic, [Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — "hardcoding complex, brittle logic" as a fragility source; "less structure, more model" as capability rises.
