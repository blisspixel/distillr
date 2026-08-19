"""Wall-clock estimation for local routes.

Feature: local-speed
"""

from __future__ import annotations

import pytest

from distill.pipeline.duration_estimates import (
    SpeedCalibration,
    estimate_stage_duration,
    estimate_workflow_duration,
    format_duration,
    format_run_projection,
    load_speed_calibration,
)

# Measured on an AMD Radeon 780M, 2026-08-18.
_MEASURED = SpeedCalibration(
    model="qwen3.8:27b",
    provider="ollama",
    prefill_tokens_per_second=12.6,
    decode_tokens_per_second=3.1,
    basis="probe",
    samples={"prefill": 1, "decode": 1},
)


class TestNoFabricatedDefault:
    """An unmeasured machine must say "unknown", never guess a rate."""

    def test_a_bare_calibration_is_not_calibrated(self) -> None:
        assert SpeedCalibration().calibrated is False

    def test_one_missing_rate_is_still_uncalibrated(self) -> None:
        """Both phases are required; a prefill rate alone cannot time a run."""
        half = SpeedCalibration(prefill_tokens_per_second=12.6)
        assert half.calibrated is False

    def test_uncalibrated_estimate_reports_unknown(self) -> None:
        estimate = estimate_stage_duration("paper", SpeedCalibration(model="qwen3.8:27b"))

        assert estimate.calibrated is False
        assert estimate.expected_seconds == 0.0
        assert "unknown" in estimate.format()
        assert "qwen3.8:27b" in estimate.format()


class TestTwoRateModel:
    """Prefill and decode differ several-fold; one blended rate cannot work."""

    def test_paper_estimate_matches_the_measured_machine(self) -> None:
        # 20_000/12.6 + 3_000/3.1 = 1587 + 968 = 2555s, against a measured ~45m.
        estimate = estimate_stage_duration("paper", _MEASURED)

        assert estimate.calibrated is True
        assert estimate.expected_seconds == pytest.approx(2555, rel=0.01)

    def test_a_blended_rate_would_be_badly_wrong(self) -> None:
        """Guards the design decision, not just the arithmetic."""
        blended = (20_000 + 3_000) / ((20_000 / 12.6) + (3_000 / 3.1))
        naive_seconds = 23_000 / blended
        two_rate = estimate_stage_duration("paper", _MEASURED).expected_seconds

        assert naive_seconds == pytest.approx(two_rate, rel=0.01)  # identical here...
        # ...but a single *decode* rate, the intuitive shortcut, is 3x off.
        decode_only = 23_000 / 3.1
        assert decode_only > two_rate * 2.5

    def test_band_brackets_the_expected_value(self) -> None:
        estimate = estimate_stage_duration("paper", _MEASURED)

        assert estimate.low_seconds < estimate.expected_seconds < estimate.high_seconds

    def test_unknown_stage_is_not_guessed(self) -> None:
        assert estimate_stage_duration("no_such_stage", _MEASURED).calibrated is False


class TestWorkflowDuration:
    """A run is many stages, and a local provider runs them one at a time."""

    def test_ten_papers_is_ten_times_one(self) -> None:
        one = estimate_stage_duration("paper", _MEASURED).expected_seconds
        ten = estimate_workflow_duration({"paper": 10}, _MEASURED).expected_seconds

        assert ten == pytest.approx(one * 10, rel=0.01)

    def test_workers_never_divide_the_estimate(self) -> None:
        """A local runtime serializes, so concurrency buys waiting, not speed."""
        serial = estimate_workflow_duration({"paper": 4}, _MEASURED, serialized=True)
        claimed_parallel = estimate_workflow_duration({"paper": 4}, _MEASURED, serialized=False)

        assert serial.expected_seconds == claimed_parallel.expected_seconds

    def test_cold_load_is_charged_once_per_run(self) -> None:
        with_load = SpeedCalibration(
            model="m",
            prefill_tokens_per_second=12.6,
            decode_tokens_per_second=3.1,
            cold_load_seconds=40.0,
            basis="probe",
        )
        one = estimate_workflow_duration({"paper": 1}, with_load).expected_seconds
        two = estimate_workflow_duration({"paper": 2}, with_load).expected_seconds

        assert two - one == pytest.approx(
            estimate_stage_duration("paper", with_load).expected_seconds, rel=0.01
        )

    def test_empty_and_zero_counts_are_unknown_not_zero(self) -> None:
        assert estimate_workflow_duration({}, _MEASURED).calibrated is False
        assert estimate_workflow_duration({"paper": 0}, _MEASURED).calibrated is False


class TestFormatDuration:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        ((0, "0s"), (45, "45s"), (60, "1m"), (125, "2m05s"), (3600, "1h"), (5100, "1h25m")),
    )
    def test_renders_readable_durations(self, seconds: float, expected: str) -> None:
        assert format_duration(seconds) == expected

    def test_nonsense_durations_are_unknown(self) -> None:
        assert format_duration(float("nan")) == "unknown"
        assert format_duration(float("inf")) == "unknown"
        assert format_duration(-5) == "unknown"


class TestLoadSpeedCalibration:
    def test_missing_file_is_uncalibrated(self, tmp_path) -> None:
        loaded = load_speed_calibration(tmp_path, model="qwen3.8:27b", provider="ollama")
        assert loaded.calibrated is False
        assert loaded.model == "qwen3.8:27b"

    def test_latest_matching_success_row_wins(self, tmp_path) -> None:
        bench = tmp_path / ".distill" / "bench"
        bench.mkdir(parents=True)
        (bench / "results.jsonl").write_text(
            "\n".join(
                [
                    '{"outcome":"success","model":"qwen3.8:27b","provider":"ollama",'
                    '"prefill_tokens_per_second":10.0,"decode_tokens_per_second":2.0,'
                    '"load_plus_queue_seconds":5.0}',
                    '{"outcome":"success","model":"qwen3.8:27b","provider":"ollama",'
                    '"prefill_tokens_per_second":49.46,"decode_tokens_per_second":5.41,'
                    '"load_plus_queue_seconds":20.51}',
                    '{"outcome":"success","model":"qwen3-coder:30b","provider":"ollama",'
                    '"prefill_tokens_per_second":189.0,"decode_tokens_per_second":21.0,'
                    '"load_plus_queue_seconds":16.0}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        loaded = load_speed_calibration(tmp_path, model="qwen3.8:27b", provider="ollama")
        assert loaded.calibrated is True
        assert loaded.decode_tokens_per_second == 5.41
        assert loaded.cold_load_seconds == 20.51

    def test_non_finite_helpers_and_provider_mismatch(self, tmp_path) -> None:
        from distill.pipeline.duration_estimates import (
            _finite_non_negative,
            _finite_positive,
        )

        assert _finite_positive(True) is None
        assert _finite_positive(0) is None
        assert _finite_positive(float("inf")) is None
        assert _finite_positive(12.0) == 12.0
        assert _finite_non_negative(True) == 0.0
        assert _finite_non_negative(-4) == 0.0
        assert _finite_non_negative(float("nan")) == 0.0
        assert _finite_non_negative(2.5) == 2.5

        bench = tmp_path / ".distill" / "bench"
        bench.mkdir(parents=True)
        (bench / "results.jsonl").write_text(
            "\n".join(
                [
                    '{"outcome":"success","model":"qwen3.8:27b","provider":"ollama",'
                    '"prefill_tokens_per_second":12.0,"decode_tokens_per_second":3.0}',
                    '{"outcome":"success","model":"qwen3.8:27b","provider":"lmstudio",'
                    '"prefill_tokens_per_second":10.0,"decode_tokens_per_second":5.0}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        loaded = load_speed_calibration(tmp_path, model="qwen3.8:27b", provider="ollama")
        assert loaded.calibrated is True
        assert loaded.decode_tokens_per_second == 3.0

    def test_bool_or_blank_identity_rows_are_uncalibrated(self, tmp_path) -> None:
        bench = tmp_path / ".distill" / "bench"
        bench.mkdir(parents=True)
        (bench / "results.jsonl").write_text(
            '{"outcome":"success","model":"qwen3.8:27b","provider":"ollama",'
            '"prefill_tokens_per_second":true,"decode_tokens_per_second":5.0}\n',
            encoding="utf-8",
        )
        assert (
            load_speed_calibration(tmp_path, model="qwen3.8:27b", provider="ollama").calibrated
            is False
        )
        assert load_speed_calibration(tmp_path, model="", provider="ollama").calibrated is False

    def test_failed_or_zero_rate_rows_are_skipped(self, tmp_path) -> None:
        bench = tmp_path / ".distill" / "bench"
        bench.mkdir(parents=True)
        (bench / "results.jsonl").write_text(
            '{"outcome":"error","model":"qwen3.8:27b","provider":"ollama",'
            '"prefill_tokens_per_second":49.0,"decode_tokens_per_second":5.0}\n',
            encoding="utf-8",
        )
        loaded = load_speed_calibration(tmp_path, model="qwen3.8:27b", provider="ollama")
        assert loaded.calibrated is False


class TestFormatRunProjection:
    def test_cloud_route_warns_that_spend_is_metered_api_billing(self) -> None:
        line = format_run_projection(
            cost_usd=1.2,
            duration=estimate_stage_duration("paper", _MEASURED),
            local=False,
        )
        assert line.startswith("Projected spend $1.20 on a metered cloud API.")
        assert "token billing" in line
        assert "not local $0" in line
        assert "quota CLIs" in line
        assert "no-metered" in line
        assert "hour" not in line

    def test_local_calibrated_route_states_time_as_the_budget(self) -> None:
        line = format_run_projection(
            cost_usd=0.0,
            duration=estimate_workflow_duration({"paper": 2, "synthesis": 1}, _MEASURED),
            local=True,
        )
        assert line.startswith("Projected spend $0.00 · ~")
        assert "qwen3.8:27b" in line
        assert "wall clock is the budget" in line
        assert "hours are expected" in line

    def test_local_uncalibrated_points_at_bench(self) -> None:
        line = format_run_projection(
            cost_usd=0.0,
            duration=estimate_stage_duration("paper", SpeedCalibration(model="qwen3.8:27b")),
            local=True,
        )
        assert "unknown" in line
        assert "distill bench" in line


class TestFormatting:
    def test_calibrated_estimate_states_its_band_and_sample_count(self) -> None:
        rendered = estimate_stage_duration("paper", _MEASURED).format()

        assert rendered.startswith("~")
        assert "est;" in rendered
        assert "sample(s)" in rendered

    def test_uncalibrated_workflow_estimate_reports_unknown(self) -> None:
        blank = SpeedCalibration(model="m:8b")

        assert estimate_workflow_duration({"paper": 3}, blank).format().startswith("unknown")
