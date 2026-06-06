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
from typing import Any

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


def interaction_text(interaction: Any) -> str:
    """Extract the model's text answer from a completed interaction.

    google-genai 2.7+ exposes the answer as ``steps`` -- the final
    ``ModelOutputStep`` (``type == "model_output"``) carries ``content``, a list
    of typed parts whose text variant is ``TextContent`` (``type == "text"``).
    Older SDKs exposed ``outputs`` instead; that path is kept as a fallback.
    Returns ``""`` when no text is present.
    """
    steps = getattr(interaction, "steps", None) or []
    model_outputs = [s for s in steps if getattr(s, "type", None) == "model_output"]
    if model_outputs:
        parts = getattr(model_outputs[-1], "content", None) or []
        text = "".join(
            part.text
            for part in parts
            if getattr(part, "type", None) == "text" and getattr(part, "text", None)
        )
        if text:
            return text

    # Legacy google-genai (< 2.7): the answer lived in outputs[-1].text.
    legacy = getattr(interaction, "outputs", None)
    if legacy:
        return getattr(legacy[-1], "text", "") or ""

    return ""


def await_interaction(
    client: Any,
    interaction_id: str,
    console: Console,
    *,
    label: str,
    poll_secs: int = 15,
) -> Any | None:
    """Poll a background interaction until it reaches a terminal state.

    Returns the interaction when it ``completed``; returns ``None`` for every
    other terminal status (after surfacing the actual status to the console),
    so the caller can clean up and bail. Polls only while the status is in
    :data:`POLLING_STATUSES`; any other status -- including one this code does
    not recognize -- is treated as terminal and ends the loop. The caller keeps
    ownership of its own cleanup (e.g. deleting the File Search store).
    """
    poll = 0
    while True:
        interaction = client.interactions.get(interaction_id)
        status = interaction.status
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
