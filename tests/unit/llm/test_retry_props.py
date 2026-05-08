"""Property-based tests for retry delay bounds.

Feature: living-wiki-0-7, Property 11: Retry delay bounds
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from distill.llm.retry import compute_delay


class TestRetryDelayBounds:
    """Property 11: Retry delay bounds.

    For any attempt n >= 0 with base_delay=2.0 and jitter_fraction=0.5,
    compute_delay(n) returns a value in [base_delay * 2^n, base_delay * 2^n * 1.5].

    **Validates: Requirements 9.1, 9.2**
    """

    @given(attempt=st.integers(min_value=0, max_value=10))
    @settings(max_examples=100)
    def test_delay_within_bounds_default_params(self, attempt: int) -> None:
        """Delay is in [base_delay * 2^n, base_delay * 2^n * 1.5] with defaults."""
        base_delay = 2.0
        jitter_fraction = 0.5

        delay = compute_delay(attempt, base_delay=base_delay, jitter_fraction=jitter_fraction)

        lower_bound = base_delay * (2**attempt)
        upper_bound = base_delay * (2**attempt) * (1 + jitter_fraction)

        assert delay >= lower_bound, (
            f"Delay {delay} below lower bound {lower_bound} for attempt {attempt}"
        )
        assert delay <= upper_bound, (
            f"Delay {delay} above upper bound {upper_bound} for attempt {attempt}"
        )

    @given(
        attempt=st.integers(min_value=0, max_value=10),
        base_delay=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
        jitter_fraction=st.floats(
            min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    def test_delay_within_bounds_arbitrary_params(
        self, attempt: int, base_delay: float, jitter_fraction: float
    ) -> None:
        """Delay is in [base_delay * 2^n, base_delay * 2^n * (1 + jitter_fraction)]."""
        delay = compute_delay(attempt, base_delay=base_delay, jitter_fraction=jitter_fraction)

        lower_bound = base_delay * (2**attempt)
        upper_bound = base_delay * (2**attempt) * (1 + jitter_fraction)

        assert delay >= lower_bound - 1e-10, (
            f"Delay {delay} below lower bound {lower_bound} for attempt {attempt}"
        )
        assert delay <= upper_bound + 1e-10, (
            f"Delay {delay} above upper bound {upper_bound} for attempt {attempt}"
        )
