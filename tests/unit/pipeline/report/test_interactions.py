"""Tests for the google-genai Interactions boundary helpers.

These pin the helpers to the real google-genai 2.7+ response shape
(``steps[].content[].text``) and the full status enum, so the false-green class
of bug (test doubles encoding a dead contract) cannot recur here. The status
list mirrors ``google.genai._interactions.types.Interaction.status``:
``in_progress, requires_action, completed, failed, cancelled, incomplete,
budget_exceeded``.
"""

import io
from types import SimpleNamespace

import pytest
from rich.console import Console

from distill.pipeline.report._interactions import (
    POLLING_STATUSES,
    await_interaction,
    interaction_text,
)


def _console() -> tuple[Console, io.StringIO]:
    """A real rich Console writing to a buffer, so output is inspectable."""
    buf = io.StringIO()
    return Console(file=buf, width=200, force_terminal=False, no_color=True), buf


def _text_part(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _model_output(*texts: str) -> SimpleNamespace:
    return SimpleNamespace(type="model_output", content=[_text_part(t) for t in texts])


# ── interaction_text ──────────────────────────────────────────────────


def test_interaction_text_reads_steps_model_output():
    interaction = SimpleNamespace(steps=[_model_output("the report body")])
    assert interaction_text(interaction) == "the report body"


def test_interaction_text_joins_multiple_text_parts():
    interaction = SimpleNamespace(steps=[_model_output("part one ", "part two")])
    assert interaction_text(interaction) == "part one part two"


def test_interaction_text_takes_last_model_output_step():
    interaction = SimpleNamespace(steps=[_model_output("draft"), _model_output("final answer")])
    assert interaction_text(interaction) == "final answer"


def test_interaction_text_ignores_non_model_output_and_non_text():
    interaction = SimpleNamespace(
        steps=[
            SimpleNamespace(type="thought", summary="thinking"),
            SimpleNamespace(type="file_search_call", id="fs-1"),
            SimpleNamespace(
                type="model_output",
                content=[
                    SimpleNamespace(type="image", data=b""),
                    _text_part("real answer"),
                ],
            ),
        ]
    )
    assert interaction_text(interaction) == "real answer"


def test_interaction_text_legacy_outputs_fallback():
    # Older google-genai (< 2.7) exposed outputs[-1].text and no steps.
    interaction = SimpleNamespace(steps=[], outputs=[SimpleNamespace(text="legacy body")])
    assert interaction_text(interaction) == "legacy body"


def test_interaction_text_empty_returns_empty_string():
    assert interaction_text(SimpleNamespace(steps=[])) == ""
    assert interaction_text(SimpleNamespace()) == ""
    assert interaction_text(SimpleNamespace(steps=[_model_output()])) == ""


# ── await_interaction ─────────────────────────────────────────────────


class _FakeClient:
    def __init__(self, states: list[SimpleNamespace]) -> None:
        self._states = states
        self.interactions = SimpleNamespace(get=self._get)

    def _get(self, _interaction_id: str) -> SimpleNamespace:
        return self._states.pop(0)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("distill.pipeline.report._interactions.time.sleep", lambda _s: None)


def test_await_interaction_returns_completed_interaction():
    completed = SimpleNamespace(status="completed", steps=[_model_output("done")])
    client = _FakeClient([completed])
    console, _buf = _console()
    result = await_interaction(client, "job-1", console, label="Research")
    assert result is completed
    assert interaction_text(result) == "done"


def test_await_interaction_polls_through_in_progress():
    client = _FakeClient(
        [
            SimpleNamespace(status="in_progress", steps=[]),
            SimpleNamespace(status="in_progress", steps=[]),
            SimpleNamespace(status="completed", steps=[_model_output("done")]),
        ]
    )
    console, _buf = _console()
    result = await_interaction(client, "job-1", console, label="Research")
    assert result is not None
    assert result.status == "completed"


def test_await_interaction_polls_through_requires_action():
    # requires_action is an in-flight status -> keep polling, do not abort.
    assert "requires_action" in POLLING_STATUSES
    client = _FakeClient(
        [
            SimpleNamespace(status="requires_action", steps=[]),
            SimpleNamespace(status="completed", steps=[_model_output("done")]),
        ]
    )
    console, _buf = _console()
    result = await_interaction(client, "job-1", console, label="Research")
    assert result is not None


@pytest.mark.parametrize(
    "status",
    ["failed", "cancelled", "incomplete", "budget_exceeded"],
)
def test_await_interaction_terminates_on_non_completed_terminal_status(status):
    # The bug class this guards: budget_exceeded (and friends) must END the
    # loop, not poll forever. A single state in the queue means a second get()
    # would raise IndexError -- so reaching the return proves no extra poll.
    console, buf = _console()
    client = _FakeClient([SimpleNamespace(status=status, steps=[])])
    result = await_interaction(client, "job-1", console, label="Research")
    assert result is None
    assert status in buf.getvalue()


def test_await_interaction_fails_closed_on_unknown_status():
    # A status this code has never seen (the next budget_exceeded) is treated
    # as terminal rather than hanging -- fail-closed.
    client = _FakeClient([SimpleNamespace(status="some_future_status", steps=[])])
    console, _buf = _console()
    result = await_interaction(client, "job-1", console, label="Research")
    assert result is None
