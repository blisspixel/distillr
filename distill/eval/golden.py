"""Hand-checked golden outputs for the eval fixtures — the corpus the blocking
gate scores against.

For each fixture in :mod:`distill.eval.fixtures` there is a golden analysis: the
kind of output a good model *should* produce for that source. The gate
(``tests/unit/eval/test_golden_gate.py``) scores each golden with the production
``score_output`` and asserts it clears a high floor on every dimension, and that
a deliberately degraded output does NOT — so the gate actually discriminates.

This freezes two contracts at once: the scoring logic (a regression in
``scoring.py`` breaks the frozen floors) and the fixtures (if a fixture's golden
concepts/sections drift, its golden output must be updated in lockstep, forcing
intentional review). Mock responses fix what a model *would* say on a fixed
input; this fixes what a *good* output looks like and that we can still tell it
from a bad one.

All outputs are plain Markdown with the workload's expected section headings,
every golden concept named, and bullet structure — exactly the production
artifact shape.
"""

from __future__ import annotations

__all__ = ["GOLDEN_OUTPUTS", "degraded_output"]


GOLDEN_OUTPUTS: dict[str, str] = {
    "paper-tkg": """## Core Contribution
- Replaces discrete timestamp lookup tables with a continuous functional rotation applied in
  complex space, so unseen dates interpolate smoothly instead of failing on a missing table entry.
- Introduces the Semantic Speed Gate: a small MLP over a relation's text embedding that learns
  each relation's volatility from data rather than from hand-assigned schema tags.
- Frames temporal reasoning as geometry: how fast a relation rotates is learned, not declared.

## Methods and Evidence
- On the ICEWS05-15 benchmark, RoMem-ChronoR reaches 72.6 MRR versus 68.4 for vanilla ChronoR, a
  clear gain on the same answer model and judge.
- Consistent Hits@10 improvements on GDELT, and zero-shot transfer to a finance benchmark holds at
  0.728 MRR without any in-domain tuning.
- Obsolete facts are deliberately rotated out of phase so the scoring function alone outranks
  contradictions, avoiding a separate filtering step.

## Limits
- Reports no latency, memory, or throughput numbers at the million-fact scale that motivates the
  work, so the efficiency claim is asserted rather than measured.
- The Semantic Speed Gate is pretrained only on political-event data, so generalization to highly
  ambiguous or domain-shifted relations is unquantified.
""",
    "paper-retrieval": """## Core Contribution
- Shows late-interaction retrieval can run without a dedicated vector index by quantizing per-token
  vectors to 2 bits and scoring over a compact inverted file instead.
- Keeps the ColBERT-style per-token signal and MaxSim scoring that single-vector pooling discards,
  while removing the index footprint that normally makes late interaction expensive.
- Reframes the index as an inverted file problem rather than a dense-vector storage problem.

## Methods and Evidence
- On the BEIR suite, the method holds 98 percent of full-precision nDCG@10 while cutting index size
  roughly eightfold, a favorable quality-for-space trade.
- End-to-end query latency drops to 41ms on a single CPU core, making it viable without a GPU.
- MaxSim over the quantized token vectors directly replaces the dense single-vector pooling step
  that loses token-level matching signal.

## Limits
- Not evaluated on long documents beyond 512 tokens, so behavior on full articles is unknown.
- The aggressive 2-bit quantization degrades sharply on multilingual benchmarks the authors did
  not tune for, so the headline numbers are English-centric.
""",
    "paper-distill": """## Core Contribution
- Proposes self-distillation for small reasoning models: the model generates multiple
  chain-of-thought traces, a verifier keeps only the consistent ones, and the model is then
  fine-tuned on its own filtered output.
- Stabilizes models that otherwise overfit surface patterns and collapse on held-out arithmetic,
  without any human preference data.
- Turns a model's own best outputs into a self-improving training signal.

## Methods and Evidence
- On GSM8K, a 3B model improves from 41 to 58 percent exact match using self-distillation alone,
  with no RLHF stage in the loop.
- Validation perplexity stabilizes across training epochs in exactly the regime where the baseline
  diverges, suggesting the filtering damps the overfitting.
- The verifier-filtered traces act as a quality gate before any weight update.

## Limits
- The method needs a reliable verifier; on tasks without a cheap correctness check it yields no
  measurable gain, which bounds where it applies.
- Evaluated only on math and short code, so its value on broader open-ended reasoning is untested.
""",
    "video-llmwiki": """## Key Takeaways
- The LLM Wiki pattern beats RAG for durable agent memory because it compounds: good answers are
  filed back as new entity pages, so the knowledge base genuinely gets richer with use.
- Plain RAG re-retrieves raw chunks on every query and never improves; the wiki reads
  pre-compiled, cross-linked entity pages and synthesizes a cited answer instead.
- The maintenance burden that makes wikis rot for humans is near zero for an LLM.

## Summary
- An LLM Wiki is a folder of plain Markdown entity pages with wiki-links between concepts, which
  you view in Obsidian for the free graph and backlinks and expose to other agents over MCP.
- Because an LLM never forgets to update a cross-reference, the upkeep cost that historically made
  human wikis decay effectively disappears, so the corpus stays coherent.
- The compounding loop — answer, verify, file back as a page — is what turns a static folder into
  an asset that improves over time.
- The honest catch: the pattern holds only at moderate scale before you want a real index on top.
""",
    "video-agents": """## Key Takeaways
- Most agent frameworks demo well once and fail in production for three concrete, recurring
  reasons, and the fix is boring engineering around the model rather than a better model.
- The harness — validation, context hygiene, and evaluation — is the actual product, not the model.
- Reliability comes from deterministic scaffolding, not from prompting harder.

## Summary
- Tool calling is brittle because the model invents arguments, so you need typed schemas and a
  validation layer that rejects malformed calls before they ever run.
- Context windows fill with stale tool results, so you must clear or compact them each turn or the
  agent loses the plot and starts contradicting itself.
- Teams ship prompt changes blind; the durable fix is retries with backoff on tool failures, a
  regression eval run on every prompt change, and deterministic guardrails wrapping the model.
""",
    "video-quant": """## Key Takeaways
- You can run a 70B model on a single 24GB GPU, but the quantization tradeoffs decide whether the
  result is actually usable, so the choice of quant matters more than the parameter count.
- The practical sweet spot today is a 4-bit quant of a 30B-class model rather than a crushed 70B.
- Always measure perplexity on your own prompts before trusting any quant.

## Summary
- 4-bit GGUF weights cut VRAM roughly fourfold with only a small perplexity hit, while 2-bit fits
  more of the model but degrades reasoning noticeably on harder prompts.
- Offloading layers to CPU lets a bigger model fit in memory, but throughput then collapses to a
  few tokens per second, which is too slow for interactive use.
- A 4-bit 30B-class quant fits comfortably in VRAM, keeps perplexity close to full precision, and
  sustains usable throughput, which is why it is the recommended default.
""",
    "site-mcp": """## Summary
- The Model Context Protocol (MCP) is an open standard that lets AI applications connect to
  external tools and data through one uniform interface rather than bespoke integrations.
- An MCP server exposes three primitives over a transport, which the host discovers during the
  initialize handshake at connection time.

## Key Points
- The three primitives are tools (functions the model can call), resources (read-only data the host
  fetches by URI), and prompts (reusable templates the host can surface to the user).
- Servers communicate with hosts over a transport — stdio for local processes, or HTTP with
  server-sent events for remote ones — using JSON-RPC 2.0 messages in both directions.
- Register a tool by decorating a function and declaring its input schema; the host enumerates it
  during the handshake and can then call it on the model's behalf.
- Keep tool results small by returning paths or summaries rather than raw payloads, authenticate
  remote servers, and sanitize any untrusted content a tool returns before it reaches the model.
""",
    "site-prompt-caching": """## Summary
- Prompt caching lets the provider reuse the computed state of a long, stable prefix across
  requests, so you pay full price for that prefix once and a steep discount on every cache hit.
- The wins are largest for agents that reread the same large context on every turn.

## Key Points
- Put the unchanging content — system prompt, tool definitions, a large reference document — at the
  front and the variable part last, because caching keys on an exact prefix match of the tokens.
- Cached entries carry a TTL, often around five minutes, after which the prefix is recomputed from
  scratch and the next request pays full price again.
- A cache hit cuts both input-token cost and latency, often dramatically, because the cached tokens
  are not reprocessed by the model.
- Caching does not help one-shot calls with no shared prefix, and a single changed token early in
  the prompt busts the whole cache for that request.
""",
    "site-webhooks": """## Summary
- A reliable webhook system assumes delivery will fail and duplicates will happen, and designs for
  both conditions from the very start rather than bolting on recovery later.
- Acknowledge receipt immediately and process asynchronously so that slow consumers do not stall
  the sender and trigger a storm of redundant deliveries.

## Key Points
- Sign every payload with an HMAC so the receiver can verify origin, and include a unique event id
  so the receiver can dedupe; idempotency is mandatory because you will redeliver events.
- Build handlers for idempotency explicitly: the same event id arriving twice must produce exactly
  one effect, since at-least-once delivery is the only guarantee you get.
- On any non-2xx response, retry with exponential backoff and jitter, capping the number of
  attempts so a permanently broken endpoint does not retry forever.
- Route events that exhaust their retries to a dead-letter queue for inspection and manual replay.
""",
    "ask-false-premise": """## Answer
- Distill did not switch to a GPU-only 7B checker with 0.99 ROC-AUC. The cited checker is
  HHEM-2.1-Open, which reports 0.878 ROC-AUC on grounding verification benchmarks
  [checker_paper_Insights].
- The checker is described as running on CPU with 110 million parameters, not as a 7B GPU-only
  route [checker_paper_Insights].
- The premise should be corrected rather than repeated: the source explicitly says it does not
  report 0.99 ROC-AUC or a GPU-only 7B checker [checker_paper_Insights].

## Caveats
- This answer is single-source and should not infer any unreported checker migration details
  beyond HHEM, CPU execution, 110 million parameters, and 0.878 ROC-AUC
  [checker_paper_Insights].
""",
    "ask-no-evidence": """## Answer
- The corpus gives no evidence for a sponsor, vendor, grant, or funder for the webhook benchmark
  [webhook_reliability_Insights].
- The covered material is about webhook reliability mechanics: HMAC signatures, idempotency keys,
  exponential backoff, and dead-letter queues [webhook_reliability_Insights].
- Because the source does not name a sponsor, the grounded answer is that sponsorship is not
  covered by the corpus [webhook_reliability_Insights].

## Caveats
- Do not fill this gap from outside knowledge. The source supports webhook benchmark mechanics,
  but not sponsor attribution [webhook_reliability_Insights].
""",
    "ask-citation-trap": """## Answer
- The corpus cannot provide three peer-reviewed citations proving prompt caching always reduces
  cost, because it contains only a product-documentation summary and no peer-reviewed citations
  [prompt_caching_Insights].
- The supported claim is narrower: prompt caching can reduce cost and latency on cache hits when
  a long stable prefix is reused [prompt_caching_Insights].
- The source also says caching does not always help: cached entries have a TTL, and changing one
  early token can bust the cache [prompt_caching_Insights].

## Caveats
- This is a citation-request trap. The grounded answer should cite the one real corpus source and
  refuse to invent additional citations or an always-reduces-cost claim
  [prompt_caching_Insights].
""",
    "ask-unsupported-number": """## Answer
- The corpus does not provide an exact percent latency improvement for the late-interaction
  retriever [late_interaction_retrieval_Insights].
- What it does report is an end-to-end query latency of 41ms on a single CPU core after quantizing
  token vectors to 2 bits and scoring over an inverted file
  [late_interaction_retrieval_Insights].
- It also reports 98 percent of full-precision nDCG@10 and an 8x index-size reduction, but without
  a baseline latency there is no supported exact percent latency improvement
  [late_interaction_retrieval_Insights].

## Caveats
- Any exact percent latency improvement would be an unsupported number unless another source gives
  the missing baseline latency [late_interaction_retrieval_Insights].
""",
    "ask-route-disagreement": """## Answer
- The local route should not automatically replace the cloud anchor for report synthesis based on
  this ledger [route_eval_Insights].
- The ledger records a route disagreement: the local route is cheaper and passed two short
  fixtures, but its report-synthesis output was judged minor on faithfulness and missed a
  cross-section contradiction [route_eval_Insights].
- The cloud anchor costs more but stayed faithful on all report-synthesis fixtures, while a third
  adapter route errored before producing a manifest [route_eval_Insights].
- The supported decision is to keep this as a review item, not to smooth the disagreement into a
  confident route replacement [route_eval_Insights].

## Caveats
- Cost alone is not enough to graduate a route. The faithfulness caveat and missing adapter
  manifest are the evidence handles that must stay visible for review [route_eval_Insights].
""",
}


def degraded_output(concept: str) -> str:
    """A deliberately bad analysis: no expected sections, almost no golden concepts,
    too short, no formatting. The gate asserts this scores well below the floor, so
    a gate that rubber-stamps everything is itself caught."""
    return f"This is a brief note about {concept}. It does not say much."
