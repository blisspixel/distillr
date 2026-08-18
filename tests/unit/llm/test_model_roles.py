"""Named local model roles.

Feature: local-speed
"""

from __future__ import annotations

from distill.llm.model_roles import (
    ROLES,
    RoleCandidate,
    resolve_role_model,
    role_env_var,
    suggest_roles,
)

# This laptop's real inventory: capabilities from /api/show, decode from bench.
_CODER = RoleCandidate("qwen3-coder:30b", 18.6, frozenset({"completion", "tools"}), 21.8)
_THINKER = RoleCandidate(
    "qwen3.8:27b", 17.7, frozenset({"completion", "tools", "thinking", "vision"}), 5.4
)
_SMALL = RoleCandidate(
    "huihui_ai/dolphin3-abliterated:8b", 4.9, frozenset({"completion", "tools"}), 10.4
)


class TestResolution:
    def test_role_maps_to_a_conventional_env_var(self) -> None:
        assert role_env_var("deep") == "DISTILL_MODEL_DEEP"

    def test_configured_role_resolves(self) -> None:
        env = {"DISTILL_MODEL_DEEP": "qwen3.8:27b"}
        assert resolve_role_model("deep", env=env) == "qwen3.8:27b"

    def test_unset_role_falls_back(self) -> None:
        assert resolve_role_model("deep", env={}, fallback="x:1b") == "x:1b"

    def test_unknown_role_never_resolves(self) -> None:
        env = {"DISTILL_MODEL_BOGUS": "x:1b"}
        assert resolve_role_model("bogus", env=env) == ""

    def test_whitespace_only_assignment_is_treated_as_unset(self) -> None:
        env = {"DISTILL_MODEL_FAST": "   "}
        assert resolve_role_model("fast", env=env, fallback="x:1b") == "x:1b"


class TestSuggestions:
    """Suggestions must come from server facts and measurements, never names."""

    def test_deep_prefers_the_thinking_capable_model_over_the_faster_one(self) -> None:
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, _SMALL])}

        assert by_role["deep"].model == "qwen3.8:27b"
        assert "thinking-capable" in by_role["deep"].reason

    def test_fast_prefers_measured_speed_over_size(self) -> None:
        """A 30B MoE decoded 4x faster than a 27B dense model on real hardware."""
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, _SMALL])}

        assert by_role["fast"].model == "qwen3-coder:30b"  # largest, yet fastest
        assert "21.8" in by_role["fast"].reason

    def test_unmeasured_machine_falls_back_to_size_and_says_so(self) -> None:
        unmeasured = [
            RoleCandidate("big:30b", 18.6, frozenset({"completion"})),
            RoleCandidate("small:8b", 4.9, frozenset({"completion"})),
        ]
        by_role = {a.role: a for a in suggest_roles(unmeasured)}

        assert by_role["fast"].model == "small:8b"
        assert "distill bench" in by_role["fast"].reason  # points at the fix

    def test_unfiltered_is_offered_but_only_as_a_name_match(self) -> None:
        """No server fact distinguishes it, so the offer must admit its basis.

        A name pattern deciding a role would be brittle; a name pattern
        *offering* a candidate an operator confirms is a discovery aid.
        """
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, _SMALL])}

        assert "unfiltered" in ROLES
        assert by_role["unfiltered"].model == _SMALL.name
        assert "name looks like" in by_role["unfiltered"].reason

    def test_deep_falls_back_when_nothing_can_think(self) -> None:
        by_role = {a.role: a for a in suggest_roles([_CODER, _SMALL])}

        assert by_role["deep"].model == "qwen3-coder:30b"  # largest
        assert "no model here reports a reasoning trace" in by_role["deep"].reason

    def test_standard_may_equal_deep_rather_than_be_degraded_to_differ(self) -> None:
        """On a machine with one strong model, both roles honestly point at it.

        Forcing them apart would mean picking a weaker everyday default purely
        to make the roles look distinct -- the speed-over-quality bias again,
        wearing a different hat.
        """
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, _SMALL])}

        assert by_role["standard"].model == by_role["deep"].model == _THINKER.name

    def test_empty_inventory_suggests_nothing(self) -> None:
        assert suggest_roles([]) == ()

    def test_single_model_still_gets_roles(self) -> None:
        by_role = {a.role: a for a in suggest_roles([_CODER])}

        assert by_role["fast"].model == by_role["deep"].model == "qwen3-coder:30b"


class TestStandardIsQualityLedNotSpeedLed:
    """The everyday default must never be chosen for being fast.

    Speed says nothing about whether an insight is worth keeping, and the corpus
    is only as good as what gets written into it. This is the regression that
    matters most: an earlier version defined standard as "fastest capable model
    that is not the deep one", which silently made the default a speed choice.
    """

    def test_standard_does_not_pick_the_fastest_model(self) -> None:
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, _SMALL])}

        assert by_role["fast"].model == "qwen3-coder:30b"  # 21.8 tok/s
        assert by_role["standard"].model == "qwen3.8:27b"  # 5.4 tok/s, 4x slower
        assert by_role["standard"].model != by_role["fast"].model

    def test_standard_says_quality_is_unranked_without_eval(self) -> None:
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, _SMALL])}

        assert "UNRANKED" in by_role["standard"].reason
        assert "distill eval" in by_role["standard"].reason

    def test_a_model_judged_faithful_wins_the_standard_role(self) -> None:
        """The only signal allowed to rank quality is the model judge's."""
        judged = RoleCandidate(
            _SMALL.name,
            _SMALL.size_gb,
            _SMALL.capabilities,
            _SMALL.decode_tokens_per_second,
            judged_faithful=True,
        )
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, judged])}

        # Smallest and neither fastest nor most capable -- but it is the one
        # with actual evidence about the quality of its output.
        assert by_role["standard"].model == _SMALL.name
        assert "judged faithful" in by_role["standard"].reason

    def test_fast_states_it_is_not_a_quality_ranking(self) -> None:
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, _SMALL])}

        assert "not a quality ranking" in by_role["fast"].reason


class TestUnfilteredHint:
    """A name pattern may offer a candidate; it may never decide one."""

    def test_a_refusal_free_name_is_offered(self) -> None:
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, _SMALL])}

        assert by_role["unfiltered"].model == "huihui_ai/dolphin3-abliterated:8b"

    def test_the_suggestion_admits_it_is_only_a_name_match(self) -> None:
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER, _SMALL])}

        assert "name looks like" in by_role["unfiltered"].reason
        assert "confirm" in by_role["unfiltered"].reason

    def test_no_hint_match_yields_no_suggestion(self) -> None:
        roles = {a.role for a in suggest_roles([_CODER, _THINKER])}

        assert "unfiltered" not in roles

    def test_operator_can_replace_the_hint_list(self) -> None:
        env = {"DISTILL_UNFILTERED_HINTS": "coder"}
        by_role = {a.role: a for a in suggest_roles([_CODER, _THINKER], env=env)}

        assert by_role["unfiltered"].model == "qwen3-coder:30b"

    def test_blank_override_falls_back_to_the_defaults(self) -> None:
        env = {"DISTILL_UNFILTERED_HINTS": "   "}
        by_role = {a.role: a for a in suggest_roles([_CODER, _SMALL], env=env)}

        assert by_role["unfiltered"].model == _SMALL.name


class TestSettingsBackedResolution:
    """Roles live in .env, which pydantic reads; os.environ alone misses them."""

    def test_role_resolves_from_the_process_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("DISTILL_MODEL_DEEP", "qwen3.8:27b")

        assert resolve_role_model("deep") == "qwen3.8:27b"

    def test_unset_role_returns_the_fallback(self, monkeypatch) -> None:
        monkeypatch.delenv("DISTILL_MODEL_UNFILTERED", raising=False)

        assert resolve_role_model("unfiltered", fallback="x:1b") == "x:1b"

    def test_empty_candidate_list_has_no_unfiltered_match(self) -> None:
        from distill.llm.model_roles import _unfiltered_hint_match, unfiltered_hints

        assert _unfiltered_hint_match([], unfiltered_hints({})) is None
