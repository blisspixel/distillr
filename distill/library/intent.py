"""CorpusIntent: the per-corpus desired state that shapes analysis and synthesis.

A corpus is built for a *goal*, read through a *lens*, for an *audience*, at a
*rigor*. Today that intent lives only as a transient string inside ``discover``
and is dropped before analysis runs, so every per-source insight is produced with
a single fixed persona regardless of what the corpus is for. ``CorpusIntent``
makes the intent a first-class, persisted object so analysis (and later
synthesis) can adapt to it.

The model is intentionally small and string-typed at the edges: it is persisted
as JSON under ``topics/<topic>/intent.json`` and read back leniently (parse,
don't crash) so a malformed or partial file degrades to the neutral default
rather than failing a run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from distill.library.paths import atomic_write_text
from distill.prompts.lenses import DEFAULT_LENS, infer_lens, normalize_lens

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_RIGOR",
    "RIGOR_NAMES",
    "CorpusIntent",
    "intent_path",
    "load_intent",
    "make_intent",
    "save_intent",
]

RIGOR_NAMES: tuple[str, ...] = ("loose", "balanced", "strict")
DEFAULT_RIGOR = "balanced"

_INTENT_FILENAME = "intent.json"


def _normalize_rigor(rigor: str) -> str:
    candidate = (rigor or "").strip().lower()
    return candidate if candidate in RIGOR_NAMES else DEFAULT_RIGOR


@dataclass(frozen=True, slots=True)
class CorpusIntent:
    """What a corpus is for, read through which lens, for whom, at what rigor.

    Construct via :func:`make_intent` (which normalizes lens/rigor and can infer
    the lens from the goal) rather than the raw constructor.
    """

    goal: str = ""
    lens: str = DEFAULT_LENS
    audience: str = ""
    rigor: str = DEFAULT_RIGOR
    quality_bar: str = ""
    budget_usd: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def make_intent(
    goal: str = "",
    *,
    lens: str = "",
    audience: str = "",
    rigor: str = "",
    quality_bar: str = "",
    budget_usd: float | None = None,
) -> CorpusIntent:
    """Build a normalized ``CorpusIntent``, inferring the lens from the goal.

    An explicit ``lens`` always wins; when it is empty (or unknown) the lens is
    inferred from the goal text, falling back to the neutral default.
    """
    resolved_lens = normalize_lens(lens) if lens.strip() else infer_lens(goal)
    return CorpusIntent(
        goal=goal.strip(),
        lens=resolved_lens,
        audience=audience.strip(),
        rigor=_normalize_rigor(rigor),
        quality_bar=quality_bar.strip(),
        budget_usd=budget_usd,
    )


def intent_path(topic_dir: Path) -> Path:
    """Path to the intent file for a topic directory."""
    return topic_dir / _INTENT_FILENAME


def save_intent(topic_dir: Path, intent: CorpusIntent) -> Path:
    """Persist ``intent`` atomically under ``topic_dir``; returns the path."""
    path = intent_path(topic_dir)
    atomic_write_text(path, json.dumps(intent.to_dict(), indent=2, ensure_ascii=False))
    return path


def load_intent(topic_dir: Path) -> CorpusIntent | None:
    """Read the persisted intent for a topic, or ``None`` if absent/unreadable.

    Lenient by design: unknown keys are ignored, missing keys take defaults, and
    a malformed file logs a debug line and returns ``None`` rather than raising,
    so a corrupt intent never breaks a run.
    """
    path = intent_path(topic_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Ignoring unreadable intent at %s: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        logger.debug("Ignoring non-object intent at %s", path)
        return None
    base = make_intent(
        goal=str(raw.get("goal", "")),
        lens=str(raw.get("lens", "")),
        audience=str(raw.get("audience", "")),
        rigor=str(raw.get("rigor", "")),
        quality_bar=str(raw.get("quality_bar", "")),
    )
    budget = raw.get("budget_usd")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool):
        return replace(base, budget_usd=float(budget))
    return base
