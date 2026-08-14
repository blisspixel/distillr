# pyright: strict
"""Shared parse-once boundary for the google-genai Interactions API.

Gemini Deep Research runs through ``client.interactions``. The SDK's response
shape and status enum are an external boundary that has already shifted once
(google-genai 2.7 dropped ``Interaction.outputs`` in favour of ``steps``), so
both the result extraction and the poll loop live here in one place rather than
copy-pasted into every report writer. See the "parse, don't validate" principle
in the roadmap: parse the external input once, here, into a plain string.

Three functions:

- :func:`preflight_metered_interaction` checks budget compatibility before any
  client, store, upload, or interaction work.
- :func:`submit_metered_interaction` repeats admission at the provider boundary
  and records both accepted and ambiguous submissions.
- :func:`interaction_text` -- pull the model's text answer out of a completed
  interaction, tolerant of both the 2.7+ ``steps`` shape and the legacy
  ``outputs`` shape.
- :func:`await_interaction` -- poll a background interaction to a terminal
  state and return it only when it completed. Fail-closed: anything that is not
  an in-flight status is treated as terminal, so a new/unknown status (the next
  ``budget_exceeded``) ends the loop instead of polling forever.
"""

import time
from collections.abc import Callable, Sequence
from typing import cast

from rich.console import Console

from distill.pipeline.costs import CostTracker

__all__ = [
    "POLLING_STATUSES",
    "await_interaction",
    "file_search_grounding_reason",
    "interaction_text",
    "preflight_metered_interaction",
    "require_cost_tracker",
    "submit_metered_interaction",
]

# Statuses that mean "still working" -- keep polling. Everything else is
# terminal (completed/failed/cancelled/incomplete/budget_exceeded and any
# status google-genai adds later). Fail-closed by design: an unrecognized
# status exits the loop rather than hanging the run.
POLLING_STATUSES = frozenset({"in_progress", "requires_action"})
_INTERRUPTED_ACCOUNTING_NOTE = (
    "Deep Research accounting raised while preserving an active process interruption."
)


def require_cost_tracker(tracker: CostTracker | None) -> CostTracker:
    """Fail closed before a metered report path can create remote resources."""

    if tracker is None:
        raise ValueError("A CostTracker is required for metered Deep Research calls")
    return tracker


def preflight_metered_interaction(*, tracker: CostTracker, model: str) -> None:
    """Fail before remote setup if Deep Research cannot honor the run budget."""

    tracker.authorize_gemini_query(model)


def submit_metered_interaction[InteractionT](
    submit: Callable[[], InteractionT],
    *,
    tracker: CostTracker,
    model: str,
) -> InteractionT:
    """Submit one variable-price interaction with fail-closed cost accounting.

    A transport exception after request bytes leave the process cannot prove
    that the provider rejected the job. Such failures are recorded as
    ``ambiguous`` and priced conservatively so the local ledger never reports a
    known lower bound as exact spend.
    """

    preflight_metered_interaction(tracker=tracker, model=model)
    with tracker.reserve_gemini_query(model):
        try:
            interaction = submit()
        except BaseException as active_error:
            try:
                tracker.record_gemini_query(model, outcome="ambiguous")
            except BaseException:
                active_error.add_note(_INTERRUPTED_ACCOUNTING_NOTE)
            raise
        tracker.record_gemini_query(model, outcome="accepted")
    return interaction


def _attr(value: object, name: str, default: object = None) -> object:
    return cast(object, getattr(value, name, default))


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return cast(Sequence[object], value)
    return ()


def _sequence_attr(value: object, name: str) -> Sequence[object]:
    return _as_sequence(_attr(value, name))


def _get_interaction(client: object, interaction_id: str) -> object:
    get_method = _attr(_attr(client, "interactions"), "get")
    if not callable(get_method):
        raise TypeError("client.interactions.get is not callable")
    return cast(Callable[[str], object], get_method)(interaction_id)


def file_search_grounding_reason(interaction: object) -> str | None:
    """Return why a completed interaction lacks structural File Search evidence."""

    steps = _sequence_attr(interaction, "steps")
    call_ids = {
        call_id
        for step in steps
        if _attr(step, "type") == "file_search_call"
        and isinstance((call_id := _attr(step, "id")), str)
        and call_id
    }
    result_ids = {
        call_id
        for step in steps
        if _attr(step, "type") == "file_search_result"
        and isinstance((call_id := _attr(step, "call_id")), str)
        and call_id
    }
    if not call_ids.intersection(result_ids):
        return "completed interaction has no matched File Search result"

    model_outputs = [step for step in steps if _attr(step, "type") == "model_output"]
    if model_outputs:
        for part in _sequence_attr(model_outputs[-1], "content"):
            for annotation in _sequence_attr(part, "annotations"):
                if _attr(annotation, "type") != "file_citation":
                    continue
                if any(
                    isinstance((identity := _attr(annotation, name)), str) and bool(identity)
                    for name in ("document_uri", "file_name", "source", "media_id")
                ):
                    return None
    return "final model output has no file citation evidence"


def interaction_text(interaction: object) -> str:
    """Extract the model's text answer from a completed interaction.

    google-genai 2.7+ exposes the answer as ``steps`` -- the final
    ``ModelOutputStep`` (``type == "model_output"``) carries ``content``, a list
    of typed parts whose text variant is ``TextContent`` (``type == "text"``).
    Older SDKs exposed ``outputs`` instead; that path is kept as a fallback.
    Returns ``""`` when no text is present.
    """
    steps = _sequence_attr(interaction, "steps")
    model_outputs = [step for step in steps if _attr(step, "type") == "model_output"]
    if model_outputs:
        parts = _sequence_attr(model_outputs[-1], "content")
        fragments: list[str] = []
        for part in parts:
            if _attr(part, "type") != "text":
                continue
            text_part = _attr(part, "text")
            if isinstance(text_part, str) and text_part:
                fragments.append(text_part)
        text = "".join(fragments)
        if text:
            return text

    # Legacy google-genai (< 2.7): the answer lived in outputs[-1].text.
    legacy = _sequence_attr(interaction, "outputs")
    if legacy:
        legacy_text = _attr(legacy[-1], "text", "")
        return legacy_text if isinstance(legacy_text, str) else ""

    return ""


def await_interaction(
    client: object,
    interaction_id: str,
    console: Console,
    *,
    label: str,
    poll_secs: int = 15,
    max_polls: int = 240,
) -> object | None:
    """Poll a background interaction until it reaches a terminal state.

    Returns the interaction when it ``completed``; returns ``None`` for every
    other terminal status (after surfacing the actual status to the console),
    so the caller can clean up and bail. Polls only while the status is in
    :data:`POLLING_STATUSES`; any other status -- including one this code does
    not recognize -- is treated as terminal and ends the loop. The caller keeps
    ownership of its own cleanup (e.g. deleting the File Search store).

    Bounded by ``max_polls`` (default 240 = 1 hour at the 15s default) so a job
    that never advances past an in-flight status -- a server-side stall, a job
    that died without updating status -- cannot poll a paid run forever. Deep
    Research typically completes in 5-15 minutes, so the bound never trips on a
    healthy run; if it does, the function reports a timeout and returns ``None``.
    """
    status = "unknown"
    poll = 0
    while poll < max_polls:
        interaction = _get_interaction(client, interaction_id)
        status_value = _attr(interaction, "status", "unknown")
        status = status_value if isinstance(status_value, str) else "unknown"
        poll += 1

        if status == "completed":
            console.print(f"[green]{label} complete ({poll * poll_secs}s elapsed)[/green]")
            return interaction

        if status not in POLLING_STATUSES:
            console.print(f"[red]{label} ended without completing (status: {status})[/red]")
            return None

        if poll % 4 == 0:
            console.print(
                f"  [dim]{label} still running... ({poll * poll_secs}s, status: {status})[/dim]"
            )
        time.sleep(poll_secs)

    console.print(
        f"[red]{label} timed out after {max_polls * poll_secs}s without completing "
        f"(last status: {status})[/red]"
    )
    return None
