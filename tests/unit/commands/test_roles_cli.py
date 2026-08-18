"""CLI surface for local model roles.

Feature: local-speed
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.commands import roles as roles_mod

runner = CliRunner()


@pytest.fixture
def no_local_models(monkeypatch):
    """Keep the CLI off the network: no inventory, no capability probe."""
    monkeypatch.setattr(roles_mod, "_installed_candidates", list)
    return


def test_roles_lists_every_role_and_flags_unset(no_local_models, monkeypatch):
    monkeypatch.setattr(roles_mod, "resolve_role_model", lambda role, **_: "")

    result = runner.invoke(cli.app, ["roles"])

    assert result.exit_code == 0, result.output
    for role in ("fast", "standard", "deep", "unfiltered"):
        assert role in result.output
    assert "not set" in result.output


def test_roles_explains_when_no_unfiltered_candidate_matched(no_local_models, monkeypatch):
    """With nothing installed there is no name to match, so say that plainly."""
    monkeypatch.setattr(roles_mod, "resolve_role_model", lambda role, **_: "")

    result = runner.invoke(cli.app, ["roles"])

    assert "no candidate matched" in result.output


def test_roles_says_faster_is_not_better(no_local_models, monkeypatch):
    """The surface must not let speed read as a quality ranking."""
    monkeypatch.setattr(roles_mod, "resolve_role_model", lambda role, **_: "")

    result = runner.invoke(cli.app, ["roles"])

    assert "Faster is not better" in result.output


def test_roles_names_the_editable_hint_list(no_local_models, monkeypatch):
    monkeypatch.setattr(roles_mod, "resolve_role_model", lambda role, **_: "")

    result = runner.invoke(cli.app, ["roles"])

    assert "DISTILL_UNFILTERED_HINTS" in result.output


def test_roles_states_that_a_role_never_changes_the_verify_gate(no_local_models, monkeypatch):
    """The floor is the product promise; the surface must say so."""
    monkeypatch.setattr(roles_mod, "resolve_role_model", lambda role, **_: "")

    result = runner.invoke(cli.app, ["roles"])

    assert "never change the prompts" in result.output


def test_roles_set_rejects_an_unknown_role(no_local_models):
    result = runner.invoke(cli.app, ["roles", "set", "bogus", "x:1b"])

    assert result.exit_code == 2  # documented usage-error code
    assert "Unknown role" in result.output


def test_roles_set_warns_when_the_model_is_not_installed(monkeypatch, tmp_path):
    from distill.llm.model_roles import RoleCandidate

    monkeypatch.setattr(
        roles_mod,
        "_installed_candidates",
        lambda: [RoleCandidate("real:8b", 4.9, frozenset({"completion"}))],
    )
    monkeypatch.setattr(roles_mod, "env_file_path", lambda: tmp_path / ".env")
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(
        roles_mod, "set_env_var", lambda path, key, value: written.append((key, value))
    )

    result = runner.invoke(cli.app, ["roles", "set", "deep", "typo:99b"])

    assert result.exit_code == 0, result.output
    assert "not among this machine's installed" in result.output
    # Warn, do not refuse: the model may be pulled later or live elsewhere.
    assert written == [("DISTILL_MODEL_DEEP", "typo:99b")]


def test_roles_set_persists_a_known_model_without_warning(monkeypatch, tmp_path):
    from distill.llm.model_roles import RoleCandidate

    monkeypatch.setattr(
        roles_mod,
        "_installed_candidates",
        lambda: [RoleCandidate("real:8b", 4.9, frozenset({"completion"}))],
    )
    monkeypatch.setattr(roles_mod, "env_file_path", lambda: tmp_path / ".env")
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(
        roles_mod, "set_env_var", lambda path, key, value: written.append((key, value))
    )

    result = runner.invoke(cli.app, ["roles", "set", "fast", "real:8b"])

    assert result.exit_code == 0, result.output
    assert "not among" not in result.output
    assert written == [("DISTILL_MODEL_FAST", "real:8b")]


class TestInventoryAssembly:
    """Role suggestions need server capabilities and measured speed together."""

    def test_candidates_merge_sizes_capabilities_and_measured_rates(self, monkeypatch):
        monkeypatch.setattr(
            "distill.commands.eval._ollama_model_sizes", lambda: {"a:8b": 4.9, "b:30b": 18.6}
        )
        monkeypatch.setattr("distill.commands.bench.stored_decode_rates", lambda: {"b:30b": 21.8})
        monkeypatch.setattr(
            roles_mod,
            "_capabilities_for",
            lambda models: {"b:30b": frozenset({"completion", "thinking"})},
        )

        candidates = {c.name: c for c in roles_mod._installed_candidates()}

        assert candidates["b:30b"].decode_tokens_per_second == 21.8
        assert candidates["b:30b"].can_think is True
        # A model with no measurement is present but unmeasured, not assumed slow.
        assert candidates["a:8b"].decode_tokens_per_second == 0.0
        assert candidates["a:8b"].measured is False

    def test_no_installed_models_yields_no_candidates(self, monkeypatch):
        monkeypatch.setattr("distill.commands.eval._ollama_model_sizes", dict)

        assert roles_mod._installed_candidates() == []

    def test_an_unreachable_server_degrades_to_no_capabilities(self, monkeypatch):
        """Capability discovery only refines a suggestion; it must not fail the view."""

        def boom() -> None:
            raise OSError("server down")

        monkeypatch.setattr("distill.llm.providers.ollama.OllamaProvider", lambda: boom())

        assert roles_mod._capabilities_for(["a:8b"]) == {}

    def test_capabilities_are_read_from_the_server(self, monkeypatch):
        class _Probe:
            @staticmethod
            async def capabilities(model: str) -> frozenset[str]:
                return frozenset({"completion", "thinking"}) if model == "t:27b" else frozenset()

        class _Provider:
            _show = _Probe()

        monkeypatch.setattr("distill.llm.providers.ollama.OllamaProvider", _Provider)

        found = roles_mod._capabilities_for(["t:27b", "p:8b"])

        assert found["t:27b"] == frozenset({"completion", "thinking"})
        assert found["p:8b"] == frozenset()


class TestRoleOverrideOnTheGlobalCallback:
    """--role must resolve to a model, defer to --model, and fail closed."""

    def test_a_configured_role_resolves_to_its_model(self, monkeypatch):
        from distill.commands.root import _apply_role_override

        monkeypatch.setenv("DISTILL_MODEL_DEEP", "qwen3.8:27b")

        assert _apply_role_override("deep", "") == "qwen3.8:27b"

    def test_an_explicit_model_beats_a_role(self, monkeypatch):
        """Naming a model is more specific than naming a role."""
        from distill.commands.root import _apply_role_override

        monkeypatch.setenv("DISTILL_MODEL_DEEP", "qwen3.8:27b")

        assert _apply_role_override("deep", "other:8b") == "other:8b"

    def test_no_role_leaves_the_model_untouched(self):
        from distill.commands.root import _apply_role_override

        assert _apply_role_override("", "kept:8b") == "kept:8b"

    def test_a_non_string_role_is_treated_as_unset(self):
        """The callback is also invoked directly, where options arrive as sentinels."""
        from distill.commands.root import _apply_role_override

        assert _apply_role_override(object(), "kept:8b") == "kept:8b"

    def test_an_unknown_role_is_a_usage_error(self):
        import typer

        from distill.commands.root import _apply_role_override

        with pytest.raises(typer.Exit) as excinfo:
            _apply_role_override("bogus", "")

        assert excinfo.value.exit_code == 2

    def test_an_unassigned_role_fails_closed_rather_than_guessing(self, monkeypatch):
        import typer

        from distill.commands.root import _apply_role_override

        monkeypatch.delenv("DISTILL_MODEL_UNFILTERED", raising=False)

        with pytest.raises(typer.Exit) as excinfo:
            _apply_role_override("unfiltered", "")

        assert excinfo.value.exit_code == 3  # missing configuration


def test_roles_json_mode_reports_assignment_and_suggestion(monkeypatch):
    """Loops read this surface, so every role must appear with its provenance."""
    import json

    from distill.llm.model_roles import RoleCandidate

    monkeypatch.setattr(
        roles_mod,
        "_installed_candidates",
        lambda: [RoleCandidate("t:27b", 17.0, frozenset({"completion", "thinking"}), 5.4)],
    )
    monkeypatch.setattr(roles_mod, "resolve_role_model", lambda role, **_: "")

    result = runner.invoke(cli.app, ["--json", "roles"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    roles = {row["role"]: row for row in payload.get("data", payload)["roles"]}
    assert set(roles) == {"fast", "standard", "deep", "unfiltered"}
    assert roles["deep"]["suggested"] == "t:27b"
    assert roles["deep"]["configured"] is False
    assert roles["deep"]["env_var"] == "DISTILL_MODEL_DEEP"
