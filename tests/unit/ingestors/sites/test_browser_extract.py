"""Boundary tests for isolated Chromium page extraction."""

from __future__ import annotations

import pytest

from distill.ingestors.sites.browser_extract import (
    _required_integer,
    _required_mapping,
    _required_nonempty_string,
    evaluate_bounded_page,
)


@pytest.mark.parametrize(
    ("validator", "value"),
    (
        (_required_mapping, []),
        (_required_nonempty_string, ""),
        (_required_nonempty_string, 1),
        (_required_integer, "1"),
    ),
)
def test_chromium_response_validators_reject_malformed_values(validator, value) -> None:
    with pytest.raises(TypeError, match="malformed extraction response"):
        validator(value)


def test_bounded_page_evaluation_detaches_after_malformed_protocol_response() -> None:
    class Session:
        detached = False

        @staticmethod
        def send(_method: str, *_args) -> object:
            return {"frameTree": "malformed"}

        def detach(self) -> None:
            self.detached = True

    session = Session()

    class Context:
        @staticmethod
        def new_cdp_session(_page) -> Session:
            return session

    class Page:
        context = Context()

    assert evaluate_bounded_page(Page(), expression="1", timeout_ms=100) is None
    assert session.detached is True


def test_bounded_page_evaluation_handles_session_creation_failure() -> None:
    class Context:
        @staticmethod
        def new_cdp_session(_page) -> object:
            raise RuntimeError("Chromium closed")

    class Page:
        context = Context()

    assert evaluate_bounded_page(Page(), expression="1", timeout_ms=100) is None
