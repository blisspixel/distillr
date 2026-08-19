"""Overnight profile packing: due work that fits the remaining hours."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from distill.library.profiles import list_research_profile_paths
from distill.pipeline.duration_estimates import SpeedCalibration
from distill.pipeline.profile_refresh import pack_profile_refresh

_NOW = datetime(2026, 8, 19, 6, 0, tzinfo=UTC)
_FAST = SpeedCalibration(
    model="qwen3.8:27b",
    provider="ollama",
    prefill_tokens_per_second=200.0,
    decode_tokens_per_second=50.0,
    basis="probe",
    samples={"prefill": 1, "decode": 1},
)


def _write_profile(
    library: Path,
    name: str,
    *,
    cadence: str = "daily",
    stale_after: str = "P1D",
    cost_mode: str = "no-metered",
) -> None:
    profiles = library / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (library / "goals").mkdir(parents=True, exist_ok=True)
    (library / "goals" / f"{name}.md").write_text("goal", encoding="utf-8")
    metered = "0" if cost_mode == "no-metered" else "1"
    (profiles / f"{name}.yaml").write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                f"name: {name}",
                f"topic: {name}",
                f"goal_file: goals/{name}.md",
                f"cost_mode: {cost_mode}",
                "freshness:",
                f"  cadence: {cadence}",
                f"  stale_after: {stale_after}",
                "queries:",
                "  - overnight wiki fuel",
                "limits:",
                "  max_new_items: 25",
                f"  max_metered_usd: {metered}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_list_research_profile_paths_caps_and_dedupes(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "alpha.yaml").write_text("x", encoding="utf-8")
    (profiles / "alpha.yml").write_text("y", encoding="utf-8")
    (profiles / "notes.txt").write_text("z", encoding="utf-8")
    found = list_research_profile_paths(tmp_path)
    assert [path.name for path in found] == ["alpha.yaml"]


def test_packs_never_run_daily_profiles_into_the_hour_budget(tmp_path: Path) -> None:
    _write_profile(tmp_path, "alpha")
    _write_profile(tmp_path, "bravo")
    _write_profile(tmp_path, "charlie")
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=1.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=_FAST,
    )
    # 3 paper-like items + synthesis at 200/50 tok/s is a few minutes, so all
    # three never-run daily profiles fit a 1h window.
    assert [slot.name for slot in plan.selected] == ["alpha", "bravo", "charlie"]
    assert plan.estimated_calibrated is True
    assert plan.local is True


def test_time_budget_defers_overflow_profiles(tmp_path: Path) -> None:
    slow = SpeedCalibration(
        model="qwen3.8:27b",
        provider="ollama",
        prefill_tokens_per_second=12.6,
        decode_tokens_per_second=3.1,
        basis="probe",
        samples={"prefill": 1, "decode": 1},
    )
    _write_profile(tmp_path, "alpha")
    _write_profile(tmp_path, "bravo")
    _write_profile(tmp_path, "charlie")
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=slow,
    )
    assert plan.selected
    assert any(slot.skip_reason == "time_budget" for slot in plan.deferred)
    assert (
        len(plan.selected)
        + len([slot for slot in plan.deferred if slot.skip_reason == "time_budget"])
        == 3
    )


def test_skips_paid_ok_profiles_under_no_metered(tmp_path: Path) -> None:
    _write_profile(tmp_path, "cloud", cost_mode="paid-ok")
    _write_profile(tmp_path, "local", cost_mode="no-metered")
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=_FAST,
    )
    assert [slot.name for slot in plan.selected] == ["local"]
    skipped = [slot for slot in plan.deferred if slot.name == "cloud"]
    assert skipped and skipped[0].skip_reason == "metered"


def test_skips_manual_and_fresh_profiles_by_default(tmp_path: Path) -> None:
    _write_profile(tmp_path, "once", cadence="manual")
    _write_profile(tmp_path, "daily")
    state_dir = tmp_path / ".distill" / "profiles" / "daily"
    state_dir.mkdir(parents=True)
    (state_dir / "run_state.json").write_text(
        """
        {
          "schema_version": "profile-run-state.v1",
          "profile": "daily",
          "topic": "daily",
          "last_run_at": "2026-08-19T05:00:00Z",
          "last_run": {
            "status": "ok",
            "max_metered_usd": 0,
            "metered_spend_usd": 0,
            "metered_spend_verified": true,
            "started_at": "2026-08-19T04:50:00Z",
            "finished_at": "2026-08-19T05:00:00Z"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=_FAST,
    )
    assert plan.selected == []
    reasons = {slot.name: slot.skip_reason for slot in plan.deferred}
    assert reasons["once"] == "manual"
    assert reasons["daily"] == "fresh"


def test_profile_cap_defers_the_rest(tmp_path: Path) -> None:
    for name in ("a", "b", "c"):
        _write_profile(tmp_path, name)
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=2,
        item_limit=3,
        now=_NOW,
        calibration=_FAST,
    )
    assert len(plan.selected) == 2
    assert any(slot.skip_reason == "profile_cap" for slot in plan.deferred)


def _write_run_state(
    library: Path,
    name: str,
    *,
    status: str = "ok",
    last_run_at: str = "2026-08-18T05:00:00Z",
    started_at: str = "2026-08-18T04:00:00Z",
    finished_at: str = "2026-08-18T05:00:00Z",
) -> None:
    state_dir = library / ".distill" / "profiles" / name
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "run_state.json").write_text(
        "\n".join(
            [
                "{",
                '  "schema_version": "profile-run-state.v1",',
                f'  "profile": "{name}",',
                f'  "topic": "{name}",',
                f'  "last_run_at": "{last_run_at}",',
                '  "last_run": {',
                f'    "status": "{status}",',
                '    "max_metered_usd": 0,',
                '    "metered_spend_usd": 0,',
                '    "metered_spend_verified": true,',
                f'    "started_at": "{started_at}",',
                f'    "finished_at": "{finished_at}"',
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )


def test_failed_profile_outranks_stale_and_is_selected(tmp_path: Path) -> None:
    _write_profile(tmp_path, "broken")
    _write_profile(tmp_path, "stale")
    _write_run_state(tmp_path, "broken", status="failed")
    _write_run_state(tmp_path, "stale", status="ok")
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=_FAST,
    )
    assert [slot.name for slot in plan.selected] == ["broken", "stale"]
    assert plan.selected[0].reason == "failed"
    assert plan.selected[1].reason == "stale"


def test_invalid_profile_is_deferred_not_started(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "broken.yaml").write_text("not: valid: yaml: [\n", encoding="utf-8")
    _write_profile(tmp_path, "ok")
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=_FAST,
    )
    assert [slot.name for slot in plan.selected] == ["ok"]
    skipped = [slot for slot in plan.deferred if slot.name == "broken"]
    assert skipped and skipped[0].skip_reason == "invalid"


def test_first_overrun_profile_still_starts(tmp_path: Path) -> None:
    slow = SpeedCalibration(
        model="qwen3.8:27b",
        provider="ollama",
        prefill_tokens_per_second=1.0,
        decode_tokens_per_second=1.0,
        basis="probe",
        samples={"prefill": 1, "decode": 1},
    )
    _write_profile(tmp_path, "alpha")
    _write_profile(tmp_path, "bravo")
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=0.25,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=slow,
    )
    assert [slot.name for slot in plan.selected] == ["alpha"]
    assert any(slot.skip_reason == "time_budget" and slot.name == "bravo" for slot in plan.deferred)


def test_uncalibrated_never_run_does_not_pack_as_free(tmp_path: Path) -> None:
    _write_profile(tmp_path, "new")
    _write_profile(tmp_path, "known")
    _write_run_state(
        tmp_path,
        "known",
        last_run_at="2026-08-17T05:00:00Z",
        started_at="2026-08-17T00:00:00Z",
        finished_at="2026-08-17T05:00:00Z",
    )
    blank = SpeedCalibration(model="qwen3.8:27b", provider="ollama")
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=blank,
    )
    assert [slot.name for slot in plan.selected] == ["new"]
    deferred = [slot for slot in plan.deferred if slot.name == "known"]
    assert deferred and deferred[0].skip_reason == "time_budget"
    assert plan.selected[0].estimated_calibrated is False


def test_include_fresh_and_manual_opt_in(tmp_path: Path) -> None:
    _write_profile(tmp_path, "daily")
    _write_profile(tmp_path, "once", cadence="manual")
    _write_run_state(tmp_path, "daily", last_run_at="2026-08-19T05:00:00Z")
    both = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        include_fresh=True,
        include_manual=True,
        now=_NOW,
        calibration=_FAST,
    )
    assert {slot.name for slot in both.selected} == {"daily", "once"}
    manuals = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        include_manual=True,
        now=_NOW,
        calibration=_FAST,
    )
    assert [slot.name for slot in manuals.selected] == ["once"]
    skipped = [slot for slot in manuals.deferred if slot.name == "daily"]
    assert skipped and skipped[0].skip_reason == "fresh"


def test_corrupt_state_and_bad_timestamps_do_not_crash(tmp_path: Path) -> None:
    _write_profile(tmp_path, "garbled")
    _write_profile(tmp_path, "listed")
    _write_profile(tmp_path, "plain")
    _write_profile(tmp_path, "stale-clock")
    _write_profile(tmp_path, "inverted")
    _write_profile(tmp_path, "empty-clock")
    state_dir = tmp_path / ".distill" / "profiles"
    (state_dir / "garbled").mkdir(parents=True)
    (state_dir / "garbled" / "run_state.json").write_text("{not-json\n", encoding="utf-8")
    (state_dir / "listed").mkdir(parents=True)
    (state_dir / "listed" / "run_state.json").write_text("[]\n", encoding="utf-8")
    (state_dir / "plain").mkdir(parents=True)
    (state_dir / "plain" / "run_state.json").write_text(
        '{"schema_version":"profile-run-state.v1","profile":"plain","topic":"plain",'
        '"last_run_at":"2026-08-17T05:00:00Z","last_run":"ok"}\n',
        encoding="utf-8",
    )
    _write_run_state(tmp_path, "stale-clock", last_run_at="not-a-timestamp")
    _write_run_state(
        tmp_path,
        "inverted",
        last_run_at="2026-08-17T05:00:00Z",
        started_at="2026-08-17T06:00:00Z",
        finished_at="2026-08-17T05:00:00Z",
    )
    _write_run_state(tmp_path, "empty-clock", last_run_at="")
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=_FAST,
    )
    names = {slot.name: slot.reason for slot in plan.selected}
    assert names["garbled"] == "never_run"
    assert names["listed"] == "never_run"
    assert names["plain"] == "stale"
    assert names["empty-clock"] == "stale"
    assert names["stale-clock"] == "stale"
    assert names["inverted"] == "stale"


def test_manual_with_prior_run_is_fresh_until_opted_in(tmp_path: Path) -> None:
    _write_profile(tmp_path, "once", cadence="manual")
    _write_run_state(tmp_path, "once")
    skipped = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=_FAST,
    )
    assert skipped.selected == []
    opted = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        include_manual=True,
        now=_NOW,
        calibration=_FAST,
    )
    assert [slot.name for slot in opted.selected] == ["once"]
    assert opted.selected[0].reason == "fresh"


def test_plan_dict_names_the_schema(tmp_path: Path) -> None:
    _write_profile(tmp_path, "alpha")
    plan = pack_profile_refresh(
        tmp_path,
        cost_mode="no-metered",
        provider="ollama",
        model="qwen3.8:27b",
        max_hours=6.0,
        max_profiles=12,
        item_limit=3,
        now=_NOW,
        calibration=_FAST,
    )
    payload = plan.to_dict()
    assert payload["schema_version"] == "profile-refresh.v1"
    assert payload["selected_count"] == 1
    assert payload["local"] is True
