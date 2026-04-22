"""Deep corpus synthesis via Grok 4.20 (single large-context call).

Where `distill research-brief` uses Gemini Deep Research (web-augmented,
consulting-style compression) and `distill report` runs the 4-phase strategic
report pipeline, `distill synthesize` runs a single Grok 4.20-reasoning call
over the entire gathered corpus — no web augmentation, no compression bias,
full control over depth and structure.

Best for academic/technical corpus synthesis where the corpus IS the ground
truth and web context would add noise. Grok 4.20's 2M-token context swallows
hundreds of insight bundles in one call, and a context file sets direction.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from distill.config import DistillConfig
from distill.costs import CostTracker
from distill.research_brief import gather_topic_files
from distill.site_analysis import _call_grok, _get_client

console = Console()


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
    """Run a single-call Grok synthesis across the given topics."""
    if not config.xai_api_key:
        console.print("[red]XAI_API_KEY not set in .env[/red]")
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

    model = config.xai_premium_model
    console.print(f"\n[cyan]Calling {model}...[/cyan]")
    console.print(f"  [dim]max_completion_tokens={max_tokens}. Expect 2-8 minutes.[/dim]\n")

    client = _get_client(config)
    result = _call_grok(
        client,
        prompt,
        model=model,
        tracker=tracker,
        call_type="synthesis",
        max_tokens=max_tokens,
    )
    if not result:
        console.print("[red]No output received from Grok[/red]")
        return None

    output_path = Path("output") / f"synthesis-{name}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    console.print(f"\n[green]Synthesis saved to:[/green] {output_path}")
    console.print(f"[dim]Size: {len(result):,} chars[/dim]")
    return output_path
