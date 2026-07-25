# pyright: strict
"""Cross-command dispatch and startup helpers.

Extracted verbatim from ``distill.commands._helpers`` to keep that module under
the per-file size cap. This is a leaf helper module: it imports only from lower
layers (config, library, pipeline, preflight, console) and never from sibling
command modules, so ``_helpers`` can re-export these names without an import
cycle. ``_preflight`` resolves ``get_config`` through a call-time import for the
same reason -- ``get_config`` lives in ``_helpers`` and must stay a leaf.
"""

import os
from collections.abc import Callable

import typer

from distill._console import console
from distill.config import DistillConfig
from distill.library.intent import CorpusIntent, load_intent
from distill.preflight import preflight_ytdlp


def _preflight() -> None:
    """Non-blocking startup nudges: a stale-yt-dlp warning and a distillr
    update-available notice. Both cached daily and individually opt-out-able
    (DISTILL_NO_PREFLIGHT / DISTILL_NO_UPDATE_CHECK)."""
    try:
        from distill.commands._helpers import get_config

        library_dir = get_config().library_dir
    except Exception:
        library_dir = None
    preflight_ytdlp(console, library_dir)
    try:
        from distill.update import check_for_update

        check_for_update(console, library_dir)
    except Exception:
        # An update check must never break a command.
        return


def run_preflight() -> None:
    """Public command startup hook for shared non-blocking preflight checks."""
    _preflight()


def _invoke_command(fn: Callable[..., object], **overrides: object) -> object:
    """Call a Typer command internally after resolving omitted defaults."""
    import inspect

    kwargs: dict[str, object] = dict(overrides)  # always honor the caller's explicit values
    for name, param in inspect.signature(fn).parameters.items():
        if name in kwargs or param.kind in (
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            continue
        default = param.default
        if isinstance(default, (typer.models.OptionInfo, typer.models.ArgumentInfo)):
            kwargs[name] = default.default
        elif default is not inspect.Parameter.empty:
            kwargs[name] = default
        # A required param with no default is left out; fn raises if truly missing.
    return fn(**kwargs)


invoke_command = _invoke_command


def resolve_intent(config: DistillConfig, topic: str) -> CorpusIntent | None:
    """Public intent-loading seam for command helpers."""
    return _resolve_intent(config, topic)


def _resolve_intent(config: DistillConfig, topic: str) -> CorpusIntent | None:
    """Load the persisted CorpusIntent for a topic, if any.

    Returns ``None`` when the topic has no saved intent so analysis falls back to
    the neutral default lens. A topic created via ``discover`` saves its intent,
    so subsequent ingests into that topic inherit the same lens automatically.
    """
    if not topic:
        return None
    return load_intent(config.topic_dir(topic))


__all__ = ["_apply_provider_override"]


def _apply_provider_override(provider_override: str) -> None:
    """Make ``--provider`` win over any configured per-workload provider.

    ``RouterConfig.resolve`` prefers ``<workload>_provider`` over the bare
    ``provider``, so setting ``DISTILL_PROVIDER`` alone left an operator's
    ``DISTILL_ANALYSIS_PROVIDER`` in charge and silently discarded the flag. With
    ``--model`` still winning (it is checked first), that produced an incoherent
    route: ``distill --provider ollama --model qwen3.5:27b`` resolved to a *cloud*
    provider running a local model id, turning an explicit "stay local" request
    into a billed API call. Blank the per-workload keys for this process so the
    flag is authoritative, mirroring ``with_model_override``'s handling of models.

    ``fallback_provider`` is deliberately untouched: it is the opt-in credit-error
    fallback, not part of route resolution.
    """
    from distill.llm.router import RouterConfig

    os.environ["DISTILL_PROVIDER"] = provider_override
    for field_name in RouterConfig.model_fields:
        if field_name.endswith("_provider") and field_name != "fallback_provider":
            os.environ[f"DISTILL_{field_name.upper()}"] = ""
