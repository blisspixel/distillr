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

_FIXTURES: dict[str, list[Fixture]] = {
    "paper": [_PAPER],
    "video": [_VIDEO],
    "site": [_SITE],
}


def load_fixtures(workload: str) -> list[Fixture]:
    """Return fixtures for a workload, or all fixtures for ``"all"``."""
    if workload == "all":
        out: list[Fixture] = []
        for w in WORKLOADS:
            out.extend(_FIXTURES.get(w, []))
        return out
    return list(_FIXTURES.get(workload, []))
