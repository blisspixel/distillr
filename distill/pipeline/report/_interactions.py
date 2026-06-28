# pyright: strict
"""Shared parse-once boundary for the google-genai Interactions API.

Gemini Deep Research runs through ``client.interactions``. The SDK's response
shape and status enum are an external boundary that has already shifted once
(google-genai 2.7 dropped ``Interaction.outputs`` in favour of ``steps``), so
both the result extraction and the poll loop live here in one place rather than
copy-pasted into every report writer. See the "parse, don't validate" principle
in the roadmap: parse the external input once, here, into a plain string.

Two functions:

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

__all__ = [
    "POLLING_STATUSES",
    "await_interaction",
    "interaction_text",
]

# Statuses that mean "still working" -- keep polling. Everything else is
# terminal (completed/failed/cancelled/incomplete/budget_exceeded and any
# status google-genai adds later). Fail-closed by design: an unrecognized
# status exits the loop rather than hanging the run.
POLLING_STATUSES = frozenset({"in_progress", "requires_action"})


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
