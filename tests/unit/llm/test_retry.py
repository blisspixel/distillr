"""Unit tests for retry behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from distill.llm.retry import PERMANENT_ERRORS, compute_delay, retry_with_backoff


class TestComputeDelay:
    """Basic unit tests for compute_delay."""

    def test_attempt_zero(self) -> None:
        delay = compute_delay(0, base_delay=2.0, jitter_fraction=0.0)
        assert delay == 2.0

    def test_attempt_one_no_jitter(self) -> None:
        delay = compute_delay(1, base_delay=2.0, jitter_fraction=0.0)
        assert delay == 4.0

    def test_attempt_two_no_jitter(self) -> None:
        delay = compute_delay(2, base_delay=2.0, jitter_fraction=0.0)
        assert delay == 8.0


class TestRetryWithBackoffSuccess:
    """Test successful call (no retry needed)."""

    @patch("distill.llm.retry.time.sleep")
    def test_successful_call_no_retry(self, mock_sleep) -> None:
        """A function that succeeds on first call should not trigger any retries."""
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            return "success"

        result = retry_with_backoff(fn)
        assert result == "success"
        assert call_count == 1
        mock_sleep.assert_not_called()


class TestRetryWithBackoffTransientFailure:
    """Test transient failure then success (counter reset)."""

    @patch("distill.llm.retry.time.sleep")
    def test_transient_failure_then_success(self, mock_sleep) -> None:
        """Function fails once then succeeds — should retry and return success."""
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("transient")
            return "recovered"

        result = retry_with_backoff(fn, max_retries=3)
        assert result == "recovered"
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @patch("distill.llm.retry.time.sleep")
    def test_single_failure_then_success(self, mock_sleep) -> None:
        """Function fails once then succeeds on second attempt."""
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("transient")
            return "ok"

        result = retry_with_backoff(fn, max_retries=3)
        assert result == "ok"
        assert call_count == 2
        assert mock_sleep.call_count == 1


class TestRetryWithBackoffExhaustion:
    """Test 3 consecutive failures (stop)."""

    @patch("distill.llm.retry.time.sleep")
    def test_all_retries_exhausted(self, mock_sleep) -> None:
        """Function always fails — should raise after max_retries + 1 attempts."""
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"fail #{call_count}")

        with pytest.raises(RuntimeError, match="fail #4"):
            retry_with_backoff(fn, max_retries=3)

        assert call_count == 4  # initial + 3 retries
        assert mock_sleep.call_count == 3


class TestRetryWithBackoffPermanentErrors:
    """Test permanent error detection (no retry on 401/403)."""

    @patch("distill.llm.retry.time.sleep")
    def test_permanent_error_no_retry(self, mock_sleep) -> None:
        """Permanent errors should raise immediately without retrying."""
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            raise PermissionError("403 Forbidden")

        def is_permanent(exc: Exception) -> bool:
            return isinstance(exc, PermissionError)

        with pytest.raises(PermissionError, match="403 Forbidden"):
            retry_with_backoff(fn, max_retries=3, is_permanent=is_permanent)

        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("distill.llm.retry.time.sleep")
    def test_permanent_error_with_status_code(self, mock_sleep) -> None:
        """Permanent errors identified by status code should not be retried."""

        class HTTPError(Exception):
            def __init__(self, status_code: int):
                self.status_code = status_code
                super().__init__(f"HTTP {status_code}")

        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            raise HTTPError(401)

        def is_permanent(exc: Exception) -> bool:
            return isinstance(exc, HTTPError) and exc.status_code in PERMANENT_ERRORS

        with pytest.raises(HTTPError, match="HTTP 401"):
            retry_with_backoff(fn, max_retries=3, is_permanent=is_permanent)

        assert call_count == 1
        mock_sleep.assert_not_called()

    @patch("distill.llm.retry.time.sleep")
    def test_transient_error_is_retried_when_not_permanent(self, mock_sleep) -> None:
        """Non-permanent errors should still be retried."""

        class HTTPError(Exception):
            def __init__(self, status_code: int):
                self.status_code = status_code
                super().__init__(f"HTTP {status_code}")

        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise HTTPError(503)
            return "recovered"

        def is_permanent(exc: Exception) -> bool:
            return isinstance(exc, HTTPError) and exc.status_code in PERMANENT_ERRORS

        result = retry_with_backoff(fn, max_retries=3, is_permanent=is_permanent)
        assert result == "recovered"
        assert call_count == 2


class TestRetryOnRetryCallback:
    """Test on_retry callback invocation with correct arguments."""

    @patch("distill.llm.retry.time.sleep")
    def test_on_retry_called_with_correct_args(self, mock_sleep) -> None:
        """on_retry should be called with (attempt, delay, error) before each retry."""
        retry_calls: list[tuple[int, float, Exception]] = []

        def on_retry(attempt: int, delay: float, error: Exception) -> None:
            retry_calls.append((attempt, delay, error))

        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError(f"error {call_count}")
            return "done"

        result = retry_with_backoff(fn, max_retries=3, on_retry=on_retry)
        assert result == "done"
        assert len(retry_calls) == 2

        # First retry: attempt=0
        assert retry_calls[0][0] == 0
        assert retry_calls[0][1] > 0  # delay is positive
        assert str(retry_calls[0][2]) == "error 1"

        # Second retry: attempt=1
        assert retry_calls[1][0] == 1
        assert retry_calls[1][1] > 0
        assert str(retry_calls[1][2]) == "error 2"

    @patch("distill.llm.retry.time.sleep")
    def test_on_retry_not_called_on_success(self, mock_sleep) -> None:
        """on_retry should not be called when the function succeeds immediately."""
        retry_calls: list = []

        def on_retry(attempt: int, delay: float, error: Exception) -> None:
            retry_calls.append((attempt, delay, error))

        result = retry_with_backoff(lambda: "ok", max_retries=3, on_retry=on_retry)
        assert result == "ok"
        assert len(retry_calls) == 0

    @patch("distill.llm.retry.time.sleep")
    def test_on_retry_not_called_on_permanent_error(self, mock_sleep) -> None:
        """on_retry should not be called when a permanent error is raised."""
        retry_calls: list = []

        def on_retry(attempt: int, delay: float, error: Exception) -> None:
            retry_calls.append((attempt, delay, error))

        def fn():
            raise PermissionError("permanent")

        def is_permanent(exc: Exception) -> bool:
            return isinstance(exc, PermissionError)

        with pytest.raises(PermissionError):
            retry_with_backoff(fn, max_retries=3, is_permanent=is_permanent, on_retry=on_retry)

        assert len(retry_calls) == 0
