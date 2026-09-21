"""Capture receipts: a URL a crawl could not read must still leave a record."""

from __future__ import annotations

import pytest

from distill.ingestors.sites.capture import (
    CAPTURE_FAILURE_DETAIL_CHARS,
    CAPTURE_OUTCOMES,
    WHOLE_CRAWL_OUTCOMES,
    CaptureFailure,
    capture_failure_from_worker,
    summarize_capture_failures,
)
from distill.ingestors.sites.scraper import SiteCrawlResult, SitePage


def _failure(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "url": "https://example.com/missing",
        "outcome": "navigation-failed",
        "detail": "TimeoutError",
        "status": 504,
        "depth": 1,
    }
    row.update(overrides)
    return row


class TestCaptureFailure:
    def test_rejects_an_unknown_outcome(self) -> None:
        with pytest.raises(ValueError, match="unknown capture outcome"):
            CaptureFailure(url="https://example.com", outcome="made-up")

    def test_metadata_omits_unknown_status_and_empty_detail(self) -> None:
        failure = CaptureFailure(url="https://example.com", outcome="empty")

        assert failure.metadata() == {
            "url": "https://example.com",
            "outcome": "empty",
            "depth": 0,
        }

    def test_metadata_carries_status_and_detail_when_known(self) -> None:
        failure = CaptureFailure(
            url="https://example.com/gone",
            outcome="navigation-failed",
            detail="HTTP 404",
            status=404,
            depth=2,
        )

        assert failure.metadata() == {
            "url": "https://example.com/gone",
            "outcome": "navigation-failed",
            "depth": 2,
            "detail": "HTTP 404",
            "status": 404,
        }

    def test_every_declared_outcome_is_constructible(self) -> None:
        for outcome in CAPTURE_OUTCOMES:
            assert CaptureFailure(url="https://example.com", outcome=outcome).outcome == outcome


class TestWorkerParsing:
    """The worker is a separate process, so its rows are untrusted input."""

    def test_parses_a_well_formed_row(self) -> None:
        parsed = capture_failure_from_worker(_failure())

        assert parsed.outcome == "navigation-failed"
        assert parsed.status == 504
        assert parsed.depth == 1

    @pytest.mark.parametrize(
        ("overrides", "match"),
        [
            ({"url": "https://example.com/" + "x" * 4096}, "url"),
            ({"url": 7}, "url"),
            ({"outcome": "not-an-outcome"}, "outcome"),
            ({"outcome": None}, "outcome"),
            ({"detail": "x" * (CAPTURE_FAILURE_DETAIL_CHARS + 1)}, "detail"),
            ({"detail": 3}, "detail"),
            ({"status": 600}, "status"),
            ({"status": True}, "status"),
            ({"status": "404"}, "status"),
            ({"depth": 5}, "depth"),
            ({"depth": True}, "depth"),
            ({"depth": -1}, "depth"),
        ],
    )
    def test_refuses_malformed_rows(self, overrides: dict[str, object], match: str) -> None:
        with pytest.raises(ValueError, match=match):
            capture_failure_from_worker(_failure(**overrides))

    def test_refuses_a_non_object_row(self) -> None:
        with pytest.raises(ValueError, match="malformed"):
            capture_failure_from_worker(["not", "an", "object"])

    def test_defaults_fill_in_for_absent_optional_fields(self) -> None:
        parsed = capture_failure_from_worker(
            {"url": "https://example.com", "outcome": "empty"},
        )

        assert parsed.detail == ""
        assert parsed.status == 0
        assert parsed.depth == 0


class TestSummaries:
    def test_counts_are_grouped_and_sorted(self) -> None:
        failures = [
            CaptureFailure(url="https://example.com/a", outcome="empty"),
            CaptureFailure(url="https://example.com/b", outcome="navigation-failed"),
            CaptureFailure(url="https://example.com/c", outcome="empty"),
        ]

        assert summarize_capture_failures(failures) == {"empty": 2, "navigation-failed": 1}

    def test_no_failures_summarizes_to_nothing(self) -> None:
        assert summarize_capture_failures([]) == {}


class TestSiteCrawlResult:
    def test_an_empty_result_reports_nothing_attempted(self) -> None:
        result = SiteCrawlResult()

        assert result.attempted == 0
        assert result.failure_counts() == {}

    def test_metadata_reconciles_attempted_captured_and_failed(self) -> None:
        page = SitePage(
            url="https://example.com/docs",
            title="Docs",
            site_name="example.com",
            page_type="page",
            text="body",
        )
        result = SiteCrawlResult(
            pages=[page],
            failures=[
                CaptureFailure(url="https://example.com/a", outcome="empty"),
                CaptureFailure(url="https://example.com/b", outcome="empty"),
            ],
        )

        metadata = result.metadata()

        assert result.attempted == 3
        assert metadata["attempted_pages"] == 3
        assert metadata["captured_pages"] == 1
        assert metadata["failed_pages"] == 2
        assert metadata["capture_failure_counts"] == {"empty": 2}
        assert [row["url"] for row in metadata["capture_failures"]] == [
            "https://example.com/a",
            "https://example.com/b",
        ]


class TestRedaction:
    """Receipts cross the same persistence boundary as every other stored URL."""

    def test_a_query_string_is_dropped_from_the_receipt_url(self) -> None:
        failure = CaptureFailure(
            url="https://example.com/docs?session=secret-token#frag",
            outcome="navigation-failed",
        )

        assert failure.redacted().url == "https://example.com/docs"

    def test_a_url_quoted_inside_exception_text_is_reduced_too(self) -> None:
        """Playwright timeouts quote the URL they were navigating to."""
        failure = CaptureFailure(
            url="https://example.com/docs",
            outcome="navigation-failed",
            detail='TimeoutError: navigating to "https://example.com/a?token=abc123" failed',
        )

        redacted = failure.redacted()

        assert "token=abc123" not in redacted.detail
        assert "https://example.com/a" in redacted.detail
        assert redacted.detail.startswith("TimeoutError:")

    def test_redaction_reaches_the_manifest_row(self) -> None:
        failure = CaptureFailure(
            url="https://example.com/x?key=secret",
            outcome="empty",
        )

        assert failure.redacted().metadata()["url"] == "https://example.com/x"

    def test_redaction_preserves_the_non_url_fields(self) -> None:
        failure = CaptureFailure(
            url="https://example.com/x?key=secret",
            outcome="navigation-failed",
            detail="HTTP 503",
            status=503,
            depth=2,
        )

        redacted = failure.redacted()

        assert redacted.outcome == "navigation-failed"
        assert redacted.status == 503
        assert redacted.depth == 2
        assert redacted.detail == "HTTP 503"

    def test_an_empty_url_stays_empty_rather_than_becoming_a_placeholder(self) -> None:
        assert CaptureFailure(url="", outcome="worker-failed").redacted().url == ""

    def test_redacted_detail_stays_within_its_bound(self) -> None:
        failure = CaptureFailure(
            url="https://example.com",
            outcome="worker-failed",
            detail="https://example.com/" + "a" * 400 + " " + "b" * 90,
        )

        assert len(failure.redacted().detail) <= CAPTURE_FAILURE_DETAIL_CHARS


class TestSeverityClassification:
    """A page that would not load is a fact, not a failed run."""

    @pytest.mark.parametrize(
        "outcome",
        ["navigation-failed", "extraction-failed", "empty", "out-of-scope"],
    )
    def test_a_per_page_outcome_does_not_stop_the_crawl(self, outcome: str) -> None:
        assert not CaptureFailure(url="https://example.com", outcome=outcome).stopped_the_crawl

    @pytest.mark.parametrize("outcome", ["budget-exhausted", "worker-failed"])
    def test_a_whole_crawl_outcome_does(self, outcome: str) -> None:
        assert CaptureFailure(url="https://example.com", outcome=outcome).stopped_the_crawl

    def test_every_outcome_is_classified_one_way_or_the_other(self) -> None:
        assert set(CAPTURE_OUTCOMES) >= WHOLE_CRAWL_OUTCOMES
