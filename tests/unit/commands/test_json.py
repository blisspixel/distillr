"""Property-based and unit tests for distill/commands/_json.py."""

from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.commands._json import (
    ExitCode,
    JsonEnvelope,
    handle_cli_error,
    map_exception_to_exit_code,
)
from distill.pipeline.costs import BudgetExceededError

# ── Property 12: JSON envelope serialization round-trip ──
# Feature: mcp-first-surface, Property 12: JSON envelope serialization round-trip
# **Validates: Requirements 12.6**


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    status=st.sampled_from(["ok", "error"]),
    data=st.one_of(
        st.none(),
        st.dictionaries(
            st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
            st.one_of(st.integers(), st.text(max_size=20), st.booleans(), st.none()),
            max_size=5,
        ),
        st.lists(st.integers(), max_size=5),
        st.text(max_size=50),
    ),
    error=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
)
def test_json_envelope_round_trip(status, data, error):
    """Property 12: JSON envelope serialization round-trip."""
    envelope = JsonEnvelope(status=status, data=data, error=error)
    serialized = envelope.to_json()
    restored = JsonEnvelope.from_json(serialized)
    assert restored.status == envelope.status
    assert restored.data == envelope.data
    assert restored.error == envelope.error


def test_json_envelope_from_json_rejects_missing_string_status():
    with pytest.raises(ValueError, match="missing string status"):
        JsonEnvelope.from_json('{"data": {"count": 1}}')


def test_json_envelope_from_json_rejects_non_string_error():
    with pytest.raises(ValueError, match="error must be a string"):
        JsonEnvelope.from_json('{"status": "error", "error": 404}')


# ── Property 7: --json flag produces valid JSON on stdout ──
# Feature: mcp-first-surface, Property 7: --json flag produces valid JSON on stdout
# **Validates: Requirements 3.1, 3.3, 3.6**


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    status=st.sampled_from(["ok", "error"]),
    data=st.one_of(
        st.none(),
        st.dictionaries(
            st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
            st.one_of(st.integers(), st.text(max_size=20)),
            max_size=3,
        ),
    ),
    error=st.one_of(st.none(), st.text(min_size=1, max_size=30)),
)
def test_json_output_is_valid_and_no_ansi(status, data, error):
    """Property 7: --json produces valid JSON with no ANSI escape sequences."""
    envelope = JsonEnvelope(status=status, data=data, error=error)
    output = envelope.to_json()
    # Must be parseable JSON
    parsed = json.loads(output)
    assert "status" in parsed
    # Must not contain ANSI escape sequences
    assert "\x1b" not in output


# ── Unit tests for ExitCode mapping ──


class TestExitCodeMapping:
    def test_config_error(self):
        configuration_error_type = type("ConfigurationError", (Exception,), {})

        code = map_exception_to_exit_code(configuration_error_type("missing key"))
        assert code == ExitCode.CONFIG_ERROR

    def test_network_error_timeout(self):
        timeout_error_type = type("TimeoutError", (Exception,), {})

        code = map_exception_to_exit_code(timeout_error_type("timed out"))
        assert code == ExitCode.NETWORK_ERROR

    def test_not_found_error(self):
        resource_not_found_error_type = type("ResourceNotFoundError", (Exception,), {})

        code = map_exception_to_exit_code(resource_not_found_error_type("topic not found"))
        assert code == ExitCode.NOT_FOUND

    def test_provider_http_statuses_map_to_documented_exit_codes(self):
        provider_error_type = type("ProviderError", (Exception,), {})

        auth = provider_error_type("invalid key")
        auth.status_code = 401
        quota = provider_error_type("credits exhausted")
        quota.code = 403
        rate_limit = provider_error_type("rate limit")
        rate_limit.status_code = 429
        missing = provider_error_type("model missing")
        missing.response = type("Response", (), {"status_code": 404})()
        outage = provider_error_type("provider outage")
        outage.status_code = 503

        assert map_exception_to_exit_code(auth) == ExitCode.CONFIG_ERROR
        assert map_exception_to_exit_code(quota) == ExitCode.CONFIG_ERROR
        assert map_exception_to_exit_code(rate_limit) == ExitCode.NETWORK_ERROR
        assert map_exception_to_exit_code(missing) == ExitCode.NOT_FOUND
        assert map_exception_to_exit_code(outage) == ExitCode.NETWORK_ERROR

    def test_usage_error(self):
        import typer

        code = map_exception_to_exit_code(typer.BadParameter("invalid"))
        assert code == ExitCode.USAGE_ERROR

    def test_runtime_error_default(self):
        code = map_exception_to_exit_code(ValueError("something broke"))
        assert code == ExitCode.RUNTIME_ERROR

    def test_budget_exceeded(self):
        code = map_exception_to_exit_code(BudgetExceededError(0.61, 0.5))
        assert code == ExitCode.BUDGET_EXCEEDED

    def test_handle_cli_error_json_mode(self, capsys):
        code = handle_cli_error(RuntimeError("boom"), json_mode=True)
        assert code == ExitCode.RUNTIME_ERROR
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["status"] == "error"
        assert "boom" in parsed["error"]

    def test_handle_cli_error_normal_mode(self, capsys):
        code = handle_cli_error(RuntimeError("boom"), json_mode=False)
        assert code == ExitCode.RUNTIME_ERROR
        captured = capsys.readouterr()
        assert "boom" in captured.err


class TestJsonEnvelope:
    def test_success_factory(self):
        env = JsonEnvelope.success({"count": 5})
        assert env.status == "ok"
        assert env.data == {"count": 5}
        assert env.error is None

    def test_fail_factory(self):
        env = JsonEnvelope.fail("something went wrong")
        assert env.status == "error"
        assert env.error == "something went wrong"

    def test_to_json_excludes_none_error(self):
        env = JsonEnvelope.success({"x": 1})
        output = json.loads(env.to_json())
        assert "error" not in output

    def test_to_json_includes_error_when_set(self):
        env = JsonEnvelope.fail("bad")
        output = json.loads(env.to_json())
        assert output["error"] == "bad"
