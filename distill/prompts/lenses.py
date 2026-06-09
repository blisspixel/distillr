"""Analysis lenses: per-corpus analytical stance and section sets.

A *lens* shapes what the per-source analysis emphasizes so the output fits the
corpus intent instead of a single fixed persona. The enterprise pre-sales
framing that used to be hardcoded into video analysis (Vendor Watch, Business
Value Signals, Customer Conversation Starters) is now the ``competitive`` lens --
one option among several -- with ``general`` the neutral default.

This module is pure string templating in the foundational ``prompts`` layer. The
``CorpusIntent`` model in ``distill.library.intent`` carries the chosen lens; the
pipeline passes ``intent.lens`` (a plain string) to the prompt builders here.
"""

__all__ = [
    "DEFAULT_LENS",
    "LENS_NAMES",
    "LENS_STANCE",
    "focus_directive",
    "infer_lens",
    "normalize_lens",
    "video_sections",
]

# Capped lens set (calibration debt is real: each lens is prompt surface the
# golden eval gate must cover). Additions are gated, mirroring the source-adapter
# cap in the roadmap.
LENS_NAMES: tuple[str, ...] = ("general", "research", "practitioner", "competitive", "academic")
DEFAULT_LENS = "general"

# One-line analyst stance per lens, prepended to per-source analysis prompts.
LENS_STANCE: dict[str, str] = {
    "general": (
        "You are a careful analyst extracting the substance of this source for a knowledgeable "
        "generalist. Capture what matters without assuming a sales, vendor, or academic framing."
    ),
    "research": (
        "You are a research analyst reading this source for a technical research corpus. Prioritize "
        "claims, methods, evidence, limitations, and open questions over business framing."
    ),
    "practitioner": (
        "You are a hands-on practitioner mining this source for how to actually do the thing. "
        "Prioritize techniques, steps, configuration, gotchas, and when-to-use over theory or "
        "market framing."
    ),
    "competitive": (
        "You are a pre-sales architect advising enterprise customers on strategy. Prioritize vendor "
        "positioning, business value, adoption signals, and competitive dynamics."
    ),
    "academic": (
        "You are a scholar reading this source for a literature review. Prioritize theoretical "
        "contribution, methodology, relation to prior work, and evidentiary rigor."
    ),
}


def normalize_lens(lens: str) -> str:
    """Return a known lens name, falling back to the neutral default."""
    candidate = (lens or "").strip().lower().replace("-", "_").replace(" ", "_")
    return candidate if candidate in LENS_NAMES else DEFAULT_LENS


# Keyword cues for inferring a lens from a free-text goal. Ordered by priority:
# the first lens with a matching cue wins, so put the most specific first.
_LENS_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "competitive",
        (
            "vendor",
            "competitor",
            "competitive",
            "market",
            "pricing",
            "enterprise",
            "customer",
            "go-to-market",
            "positioning",
            "procure",
            "buyer",
            "sales",
        ),
    ),
    (
        "academic",
        ("literature review", "lit review", "survey of", "scholarly", "peer-reviewed"),
    ),
    (
        "research",
        (
            "research",
            "prior art",
            "arxiv",
            "paper",
            "thesis",
            "state of the art",
            "evidence",
            "benchmark",
        ),
    ),
    (
        "practitioner",
        (
            "how to",
            "how-to",
            "tutorial",
            "build",
            "implement",
            "hands-on",
            "step-by-step",
            "configure",
            "deploy",
            "practical",
        ),
    ),
)


def infer_lens(goal: str) -> str:
    """Infer an analysis lens from a free-text goal, defaulting to ``general``."""
    text = (goal or "").lower()
    if not text.strip():
        return DEFAULT_LENS
    for lens, cues in _LENS_CUES:
        if any(cue in text for cue in cues):
            return lens
    return DEFAULT_LENS


def focus_directive(goal: str = "", lens: str = "") -> str:
    """Build the lens-stance + goal-focus preamble for an analysis prompt.

    Returns ``""`` when the lens is the neutral default and no goal is given, so
    callers that supply no intent (eval harness, legacy paths) get a byte-for-byte
    unchanged prompt. The goal is whitespace-collapsed and capped so a long
    goal-file does not bloat every per-source call.
    """
    resolved = normalize_lens(lens)
    focus = " ".join((goal or "").split())[:500].strip()
    if resolved == DEFAULT_LENS and not focus:
        return ""
    lines = [f"ANALYST LENS: {LENS_STANCE[resolved]}"]
    if focus:
        lines.append(
            "GOAL FOCUS: This source is part of a corpus built for the goal below. Lead with what "
            f'advances that goal; still capture other substance.\nGOAL: "{focus}"'
        )
    return "\n".join(lines) + "\n\n"


# Per-lens section sets for the 2-pass video synthesis. The ``competitive`` set
# preserves the pre-0.9.24 enterprise output exactly; every other lens drops the
# sales framing for sections that fit the subject matter.
VIDEO_SECTIONS: dict[str, str] = {
    "general": """## Summary
2-4 sentences: what this video is about, the creator's core argument or thesis, and why it matters.

## Key Points
The most important concrete claims, findings, announcements, or data points. Be specific with names, numbers, dates, and versions. Distinguish reported fact from the creator's interpretation.

## Details and Evidence
The substantive specifics worth keeping: how things work, evidence given, mechanisms, examples, and caveats. Include the numbers and named entities actually mentioned.

## Creator's Take
The creator's analytical position, attributed as their view: their thesis and reasoning, any multi-part framework (enumerate all parts), what they are bullish or bearish on, and their predictions or advice.

## Notable Specifics
Named tools, people, organizations, papers, metrics, or direct quotes worth retaining for later retrieval. Only those actually mentioned.""",
    "research": """## Summary
2-4 sentences: the core argument or contribution and why it matters.

## Claims and Findings
The substantive claims the source makes, each with the evidence given for it. Mark each as demonstrated, asserted, or speculated. Include specific numbers, datasets, and benchmarks where stated.

## Methods and Mechanisms
How the thing works, or how the creator knows what they claim: methods, architecture, experimental setup, reasoning chain. Be concrete.

## Limitations and Open Questions
Stated weaknesses, scope boundaries, and failure modes, plus gaps visible from what was and was not shown.

## Creator's Take
The creator's position, attributed as their view: thesis, reasoning, frameworks (enumerate all parts), and predictions.""",
    "practitioner": """## Summary
2-4 sentences: what this teaches and why it matters for someone doing the work.

## How It Works and Key Techniques
The core techniques, patterns, or methods demonstrated. Be concrete about the actual approach, not the motivation.

## Steps and Configuration
Concrete how-to: steps, settings, commands, parameters, tools, and sequence. Capture enough that a practitioner could act on it.

## Gotchas and When To Use
Pitfalls, failure modes, prerequisites, trade-offs, and the conditions under which this approach is or is not the right choice.

## Creator's Take
The creator's recommendations and opinions, attributed as their view: what they advise, what they are bullish or bearish on, and why.""",
    "competitive": """## Summary
2-4 sentences: what this video is about, the creator's core argument, and why it matters for enterprise strategy.

## Key Announcements
What was announced, revealed, or disclosed. For each: what it is (specific), status (GA, Preview, Announced, Rumored, Disclosed, Reported), and why it matters for enterprise customers. If none, write "None identified."

## Technical Insights
What architects and engineers need to know: architecture patterns, evaluation results, model capabilities, infrastructure decisions, and security considerations. Include specific numbers and benchmarks mentioned.

## Business Value Signals
ROI stories, cost frameworks, adoption patterns, competitive advantages, and market dynamics that would resonate in a customer conversation about strategy.

## Vendor Watch
How this shifts the competitive landscape and what vendors, labs, or orgs are emphasizing or de-emphasizing. Only discuss vendors and products ACTUALLY MENTIONED in the video; do not inject vendors the creator did not discuss.

## Creator's Take
The creator's analytical position, attributed as their view: thesis and reasoning, frameworks (enumerate all parts), bull or bear stances, and predictions.

## Customer Conversation Starters
3-5 specific talking points grounded in what the video covered. Only reference products, services, benchmarks, and facts that appear in the extracted content; do not fabricate vendor recommendations.""",
    "academic": """## Summary
2-4 sentences: the central contribution and its significance.

## Theoretical Contribution
The conceptual or theoretical contribution: the idea, model, or framework advanced, and what it adds relative to existing understanding.

## Methodology and Evidence
The methodology and the evidence offered, with specific datasets, metrics, and results where stated. Note the strength of the evidence.

## Relation to Prior Work
How this connects to, extends, or contradicts prior work and named sources actually referenced.

## Limitations and Open Questions
Stated and inferable limitations, scope boundaries, and unresolved questions.

## Creator's Take
The creator's position, attributed as their view: thesis, reasoning, and predictions.""",
}


def video_sections(lens: str = "") -> str:
    """Return the markdown section spec for the 2-pass video synthesis lens."""
    return VIDEO_SECTIONS[normalize_lens(lens)]
