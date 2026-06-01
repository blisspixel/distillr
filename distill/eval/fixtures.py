"""Frozen eval fixtures — one per analysis workload.

Each fixture is a small, fixed source plus a hand-checked golden (the concepts a
good analysis should surface, the sections it should contain, a depth floor).
Inputs are inline and compact so the eval is offline, deterministic, and cheap —
the goal is to *differentiate models on the same input*, not to analyze a whole
paper. The harness builds the real per-workload prompt from these fields.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["WORKLOADS", "Fixture", "load_fixtures"]

WORKLOADS: tuple[str, ...] = ("paper", "video", "site")


@dataclass(frozen=True)
class Fixture:
    id: str
    workload: str
    title: str
    source_text: str
    expected_sections: tuple[str, ...]
    golden_concepts: tuple[str, ...]
    min_words: int = 180
    # workload-specific context for prompt assembly
    paper_id: str = ""
    channel: str = ""
    url: str = ""
    site_name: str = ""


_PAPER = Fixture(
    id="paper-tkg",
    workload="paper",
    title="Continuous Phase Rotation for Temporal Knowledge Graphs",
    paper_id="2604.00001v1",
    expected_sections=("contribution", "method", "limit"),
    golden_concepts=("ICEWS", "MRR", "ChronoR", "Semantic Speed Gate", "GDELT"),
    source_text=(
        "We study temporal knowledge graph (TKG) link prediction. Existing methods use "
        "discrete timestamp lookup tables, which cannot interpolate unseen dates. We propose "
        "a continuous functional rotation theta_r(tau) = s * alpha_r * tau * omega applied in "
        "complex space, removing the timestamp table entirely. A Semantic Speed Gate, a small "
        "MLP over the relation's text embedding, predicts each relation's volatility alpha_r so "
        "the model learns how fast a relation rotates from data rather than schema tags. "
        "Obsolete facts are rotated out of phase so the scoring function alone outranks "
        "contradictions. On ICEWS05-15, RoMem-ChronoR reaches 72.6 MRR versus 68.4 for vanilla "
        "ChronoR; on GDELT we see consistent Hits@10 gains. Zero-shot transfer to a finance "
        "benchmark reaches 0.728 MRR. We do not report latency, memory, or throughput at "
        "million-fact scale, and the gate is pretrained only on political-event data, so "
        "generalization to highly ambiguous relations is unquantified."
    ),
)

_VIDEO = Fixture(
    id="video-llmwiki",
    workload="video",
    title="LLM Wikis vs RAG: Why Compounding Memory Wins",
    channel="Applied LLM Lab",
    expected_sections=("takeaway", "summary"),
    golden_concepts=("RAG", "LLM Wiki", "Obsidian", "MCP", "entity pages"),
    source_text=(
        "Today we compare two ways to give an agent memory. The first is RAG: every query, you "
        "embed the question, retrieve raw chunks, and stuff them in context. It works but it "
        "rediscovers everything from scratch each time and never improves. The second is the "
        "LLM Wiki pattern Karpathy described: a folder of plain Markdown entity pages the agent "
        "maintains, with wiki-links between concepts. Instead of retrieving chunks, the agent "
        "reads pre-compiled entity pages and synthesizes an answer with citations. The key win "
        "is compounding: good answers get filed back as new pages, so the knowledge base gets "
        "richer with use. You view it in Obsidian for the free graph and backlinks, and expose "
        "it to other agents over MCP. The maintenance cost that makes wikis rot for humans is "
        "near zero for an LLM, which never forgets to update a cross-reference. The catch is it "
        "only holds at moderate scale before you want an index."
    ),
)

_SITE = Fixture(
    id="site-mcp",
    workload="site",
    title="Model Context Protocol: Server Quickstart",
    url="https://example.com/docs/mcp/quickstart",
    site_name="Example Docs",
    expected_sections=("summary", "point"),
    golden_concepts=("MCP", "stdio", "tools", "resources", "JSON-RPC"),
    source_text=(
        "The Model Context Protocol (MCP) is an open standard that lets AI applications connect "
        "to external tools and data through a uniform interface. An MCP server exposes three "
        "primitives: tools (functions the model can call), resources (read-only data the host "
        "can fetch by URI), and prompts (reusable templates). Servers communicate with hosts "
        "over a transport — most commonly stdio for local processes, or HTTP with server-sent "
        "events for remote ones — using JSON-RPC 2.0 messages. To register a tool, decorate a "
        "function and declare its input schema; the host discovers it during the initialize "
        "handshake. Keep tool results small and return paths or summaries rather than raw "
        "payloads so you do not blow the host's context window. Authenticate remote servers and "
        "sanitize any untrusted content a tool returns before it reaches the model."
    ),
)

_PAPER2 = Fixture(
    id="paper-retrieval",
    workload="paper",
    title="Late-Interaction Retrieval Without a Vector Index",
    paper_id="2604.00002v1",
    expected_sections=("contribution", "method", "limit"),
    golden_concepts=("ColBERT", "BEIR", "nDCG", "MaxSim", "latency"),
    source_text=(
        "Dense retrieval usually pools a passage into one vector, losing token-level signal. "
        "Late-interaction methods like ColBERT keep per-token vectors and score with MaxSim, but "
        "the index balloons. We show a late-interaction retriever can run without a dedicated "
        "vector index by quantizing token vectors to 2 bits and scoring over an inverted file. "
        "On BEIR we hold 98 percent of full-precision nDCG@10 while cutting index size 8x. "
        "End-to-end query latency drops to 41ms on a single CPU core. We do not evaluate on "
        "long documents beyond 512 tokens, and the 2-bit quantization degrades sharply on "
        "multilingual benchmarks we did not tune for."
    ),
)

_PAPER3 = Fixture(
    id="paper-distill",
    workload="paper",
    title="Self-Distillation Stabilizes Small Reasoning Models",
    paper_id="2604.00003v1",
    expected_sections=("contribution", "method", "limit"),
    golden_concepts=("GSM8K", "self-distillation", "chain-of-thought", "perplexity", "RLHF"),
    source_text=(
        "Small models trained on chain-of-thought traces overfit to surface patterns and "
        "collapse on held-out arithmetic. We propose self-distillation: the model generates "
        "multiple reasoning traces, a verifier keeps the consistent ones, and the model is "
        "fine-tuned on its own filtered output. On GSM8K a 3B model improves from 41 to 58 "
        "percent exact match without any RLHF, and validation perplexity stabilizes across "
        "epochs where the baseline diverges. The method needs a reliable verifier; on tasks "
        "without a cheap correctness check it gives no gain, and we did not test beyond math "
        "and short code."
    ),
)

_VIDEO2 = Fixture(
    id="video-agents",
    workload="video",
    title="Why Most Agent Frameworks Fail in Production",
    channel="Build Real Agents",
    expected_sections=("takeaway", "summary"),
    golden_concepts=("tool calling", "context window", "retries", "eval", "guardrails"),
    source_text=(
        "Most agent demos work once and fail in production for three reasons. First, tool "
        "calling is brittle: the model invents arguments, so you need typed schemas and a "
        "validation layer that rejects bad calls before they run. Second, context windows fill "
        "with stale tool results; you have to clear or compact them or the agent loses the "
        "plot. Third, there is no eval: teams ship prompt changes blind. The fix is boring "
        "engineering: deterministic guardrails around the model, retries with backoff on tool "
        "failures, and a regression eval you run on every prompt change. The model is the easy "
        "part; the harness is the product."
    ),
)

_VIDEO3 = Fixture(
    id="video-quant",
    workload="video",
    title="Running 70B Models on One Consumer GPU",
    channel="Local LLM Weekly",
    expected_sections=("takeaway", "summary"),
    golden_concepts=("quantization", "VRAM", "GGUF", "throughput", "perplexity"),
    source_text=(
        "You can run a 70B model on a single 24GB GPU, but the tradeoffs matter. The trick is "
        "quantization: 4-bit GGUF weights cut VRAM roughly fourfold with a small perplexity "
        "hit, while 2-bit fits more but degrades reasoning noticeably. Offloading layers to "
        "CPU lets a bigger model fit but throughput collapses to a few tokens per second. The "
        "practical sweet spot today is a 4-bit quant of a 30B-class model: it fits in VRAM, "
        "keeps perplexity close to full precision, and sustains usable throughput. Measure "
        "perplexity on your own prompts before trusting any quant."
    ),
)

_SITE2 = Fixture(
    id="site-prompt-caching",
    workload="site",
    title="Prompt Caching: Cut Repeat-Context Costs",
    url="https://example.com/docs/prompt-caching",
    site_name="Example Docs",
    expected_sections=("summary", "point"),
    golden_concepts=("prompt caching", "cache hit", "TTL", "tokens", "latency"),
    source_text=(
        "Prompt caching lets the provider reuse the computed state of a long, stable prefix "
        "across requests, so you pay full price for it once and a steep discount on cache hits. "
        "Put the unchanging content — system prompt, tool definitions, a large document — at "
        "the front, and the variable part last, because caching keys on a prefix match. Cached "
        "entries carry a TTL, often around five minutes, after which the prefix is recomputed. "
        "Wins are largest for agents that reread the same context every turn: cache hits cut "
        "both input-token cost and latency. Caching does not help one-shot calls with no shared "
        "prefix, and a single changed token early in the prompt busts the whole cache."
    ),
)

_SITE3 = Fixture(
    id="site-webhooks",
    workload="site",
    title="Designing Reliable Webhooks",
    url="https://example.com/docs/webhooks",
    site_name="Example Docs",
    expected_sections=("summary", "point"),
    golden_concepts=("idempotency", "retries", "HMAC", "exponential backoff", "dead-letter"),
    source_text=(
        "A reliable webhook system assumes delivery will fail and duplicates will happen. Sign "
        "every payload with an HMAC so the receiver can verify origin, and include a unique "
        "event id so the receiver can dedupe — handlers must be idempotent because you will "
        "redeliver. On non-2xx responses, retry with exponential backoff and jitter, capping "
        "attempts, then route exhausted events to a dead-letter queue for manual replay. Keep "
        "handler work fast: acknowledge receipt immediately and process asynchronously, or slow "
        "consumers will trigger spurious retries and amplify load."
    ),
)

_FIXTURES: dict[str, list[Fixture]] = {
    "paper": [_PAPER, _PAPER2, _PAPER3],
    "video": [_VIDEO, _VIDEO2, _VIDEO3],
    "site": [_SITE, _SITE2, _SITE3],
}


def load_fixtures(workload: str) -> list[Fixture]:
    """Return fixtures for a workload, or all fixtures for ``"all"``."""
    if workload == "all":
        out: list[Fixture] = []
        for w in WORKLOADS:
            out.extend(_FIXTURES.get(w, []))
        return out
    return list(_FIXTURES.get(workload, []))
