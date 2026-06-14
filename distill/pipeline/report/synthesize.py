"""Deep corpus synthesis via a single large-context LLM call.

Where `distill research-brief` uses Gemini Deep Research (web-augmented,
consulting-style compression) and `distill report` runs the 4-phase strategic
report pipeline, `distill synthesize` runs a single large-context LLM call
over the entire gathered corpus — no web augmentation, no compression bias,
full control over depth and structure.

Best for academic/technical corpus synthesis where the corpus IS the ground
truth and web context would add noise.
"""

from __future__ import annotations

from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.pipeline.report.brief import gather_topic_files

__all__ = [
    "compose_synthesis_prompt",
    "run_synthesis",
]


def _synthesis_model_available() -> bool:
    """Is a model configured for the synthesis workload (cloud key OR local provider)?

    Asks the router (does ``validate_config`` pass for this workload?), never
    ``config.xai_api_key`` -- a local-only user (Ollama / LM Studio) can run
    synthesis on their own model and must not be blocked with "XAI_API_KEY not
    set". See docs/design/model-judgment-vs-brittle-fallbacks.md ("use what they
    have, never assume a cloud key").
    """
    from distill.llm.availability import model_available

    return model_available("synthesis")


def compose_synthesis_prompt(context: str, corpus_sections: list[tuple[str, str]]) -> str:
    corpus_body = "\n\n".join(
        f"=== SOURCE: {label} ===\n\n{content}" for label, content in corpus_sections
    )
    return (
        "You are producing a comprehensive research synthesis. The reader is a sophisticated "
        "technical practitioner who will make architectural decisions based on this synthesis. "
        "You have access to an extensive corpus of source material attached below. Ground every "
        "claim in that corpus. External general knowledge is acceptable only to frame or "
        "contextualize — do not introduce new findings that are not in the corpus.\n\n"
        "Prioritize depth, specificity, and usefulness over brevity. If a technique appears in a "
        "paper, describe its mechanism, the numbers or math that matter, the trade-offs, and the "
        "specific implementation considerations for the reader's context. Cite papers inline by "
        "title + arXiv ID. Use the claim-strength labels the context file specifies.\n\n"
        "=== CONTEXT AND INSTRUCTIONS ===\n\n"
        + context.strip()
        + "\n\n"
        + "=== CORPUS ===\n\n"
        + corpus_body
        + "\n\n=== END OF CORPUS ===\n\n"
        + "Now produce the synthesis. Do not summarize the corpus before beginning the synthesis — "
        "begin directly with the first required section. Use the corpus density it deserves: every "
        "section should cite 3+ distinct papers where available. Do not pad; do not compress. When "
        "the literature offers specifics (equations, benchmark numbers, named architectures, "
        "ablation results), name them explicitly."
    )


def run_synthesis(
    topics: list[str],
    context: str,
    name: str,
    config: DistillConfig,
    max_tokens: int = 32768,
    tracker: CostTracker | None = None,
) -> Path | None:
    """Run a single-call LLM synthesis across the given topics."""
    if not _synthesis_model_available():
        console.print(
            "[red]No model configured for synthesis.[/red] Set a cloud key "
            "(XAI_API_KEY / GEMINI_API_KEY) or a local provider (DISTILL_PROVIDER=ollama)."
        )
        return None

    console.print(f"[cyan]Gathering files across {len(topics)} topic(s)...[/cyan]")
    files = gather_topic_files(topics, config)
    if not files:
        console.print("[red]No content found across the given topics[/red]")
        return None

    total_chars = sum(len(content) for _, content in files)
    console.print(f"  {len(files)} documents, {total_chars:,} chars total")

    prompt = compose_synthesis_prompt(context, files)
    console.print(f"  [dim]Prompt size: {len(prompt):,} chars (~{len(prompt) // 4:,} tokens)[/dim]")

    rc = RouterConfig()
    _, model = rc.resolve("synthesis")
    console.print(f"\n[cyan]Calling {model}...[/cyan]")
    console.print(f"  [dim]max_completion_tokens={max_tokens}. Expect 2-8 minutes.[/dim]\n")

    response = llm_call(
        rc,
        workload_tag="synthesis",
        prompt=prompt,
        max_tokens=max_tokens,
        call_type="synthesis",
    )
    result = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="synthesis",
            )
        )

    if not result:
        console.print("[red]No output received from LLM[/red]")
        return None

    output_path = Path("output") / f"synthesis-{name}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    console.print(f"\n[green]Synthesis saved to:[/green] {output_path}")
    console.print(f"[dim]Size: {len(result):,} chars[/dim]")
    return output_path
