"""Unit tests for ``distill.commands.audit`` helpers and interactive paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.commands import audit as audit_mod
from distill.config import DistillConfig
from distill.library import Library
from distill.library.freshness import SynthesisFreshness
from distill.library.links import BrokenLink, LinkCheckResult
from distill.pipeline.audit import (
    AuditReport,
    StalenessRollup,
    VerifyRollup,
    build_next_action_plan,
)


def _config(tmp_path: Path) -> DistillConfig:
    return DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")


def _audit_report(**overrides) -> AuditReport:
    base = {
        "topic": "t",
        "health_warnings": [],
        "contested": [],
        "broken_links": [],
        "gaps": [],
        "next_actions": [],
        "verify": VerifyRollup(insights_total=0, checked=0, clean=0),
    }
    base.update(overrides)
    return AuditReport(**base)


def _seed_topic(config: DistillConfig, topic: str = "t") -> Path:
    lib = Library(config)
    lib.add_channel(topic, "https://www.youtube.com/@chan", "Chan")
    topic_dir = config.topic_dir(topic)
    topic_dir.mkdir(parents=True, exist_ok=True)
    return topic_dir


class TestAuditHelpers:
    def test_resolve_next_action_mode_activates_json(self, monkeypatch):
        monkeypatch.setattr(audit_mod, "set_json_mode", MagicMock())
        monkeypatch.setattr(audit_mod, "set_json_active", MagicMock())
        monkeypatch.setattr(audit_mod, "json_mode_active", lambda: False)

        next_on, wants_json = audit_mod._resolve_next_action_mode(
            json_output=True, next_actions=False
        )

        audit_mod.set_json_mode.assert_called_once_with(True)
        audit_mod.set_json_active.assert_called_once_with(True)
        assert next_on is True
        assert wants_json is True

    def test_bucket_broken_links_groups_by_topic(self):
        library = Path("library")
        broken = [
            BrokenLink(
                source_file=library / "topics" / "ai" / "note.md",
                line_number=1,
                link_text="[[missing]]",
                target_slug="missing",
            ),
            BrokenLink(
                source_file=library / "topics" / "web" / "other.md",
                line_number=2,
                link_text="[[gone]]",
                target_slug="gone",
            ),
        ]

        grouped = audit_mod._bucket_broken_links(broken)

        assert len(grouped["ai"]) == 1
        assert len(grouped["web"]) == 1
        assert grouped["ai"][0].target_slug == "missing"

    def test_emit_empty_plan(self, tmp_path, monkeypatch):
        printed: list[dict] = []
        config = _config(tmp_path)
        monkeypatch.setattr(audit_mod, "emit_json", printed.append)

        audit_mod._emit_empty_plan(config, "all", "2026-06-21T00:00:00Z")

        assert printed[0]["schema_version"] == "next-actions.v1"
        assert printed[0]["topic"] == "all"
        assert printed[0]["actions"] == []

    def test_build_report_survives_gap_summary_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        lib = Library(config)
        _seed_topic(config)

        def explode(_config, _topic):
            raise RuntimeError("gap scan failed")

        monkeypatch.setattr("distill.pipeline.gaps.topic_gap_summary", explode)

        report = audit_mod._build_report(config, lib, "t", {})

        assert report.topic == "t"
        assert report.gaps == []
        assert report.next_actions == []

    def test_build_report_skips_contested_when_topic_missing(self, tmp_path):
        config = _config(tmp_path)
        lib = Library(config)

        report = audit_mod._build_report(config, lib, "missing", {})

        assert report.contested == []

    def test_print_next_action_plan_empty(self, monkeypatch):
        console = MagicMock()
        monkeypatch.setattr(audit_mod, "console", console)
        plan = build_next_action_plan(
            Path("library"), [], topic="t", generated_at="2026-06-21T00:00:00Z"
        )

        audit_mod._print_next_action_plan(plan)

        assert any("No bounded next actions" in str(call) for call in console.print.call_args_list)

    def test_print_next_action_plan_lists_actions(self, tmp_path, monkeypatch):
        console = MagicMock()
        monkeypatch.setattr(audit_mod, "console", console)
        topic_dir = tmp_path / "library" / "topics" / "t"
        topic_dir.mkdir(parents=True)
        report = _audit_report(gaps=["Coverage is effectively single-source (papers)."])
        plan = build_next_action_plan(
            tmp_path / "library",
            [report],
            topic="t",
            generated_at="2026-06-21T00:00:00Z",
        )

        audit_mod._print_next_action_plan(plan)

        joined = " ".join(str(call) for call in console.print.call_args_list)
        assert "discover --from-gaps" in joined
        assert "distill audit t --next-actions --json" in joined

    def test_write_library_audit_quiet_and_verbose(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        config.library_dir.mkdir(parents=True)
        console = MagicMock()
        monkeypatch.setattr(audit_mod, "console", console)

        audit_mod._write_library_audit(config, "2026-06-21T00:00:00Z", quiet=True)
        assert console.print.call_count == 0
        assert (config.library_dir / "Library_Audit.md").exists()

        audit_mod._write_library_audit(config, "2026-06-21T00:00:00Z", quiet=False)
        assert console.print.call_count == 2


class TestAuditActions:
    def _link_result(self, broken: list[BrokenLink] | None = None) -> LinkCheckResult:
        return LinkCheckResult(total_links=1, broken_links=broken or [], files_scanned=1)

    def test_act_fix_links(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        console = MagicMock()
        monkeypatch.setattr(audit_mod, "console", console)
        monkeypatch.setattr("distill.library.links.fix_broken_links", lambda *_a, **_k: 2)

        audit_mod._act_fix_links(config, ["t"], [], self._link_result(), "2026-06-21T00:00:00Z")

        assert any("Fixed 2 link" in str(call) for call in console.print.call_args_list)

    def test_act_orientation(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        topic_dir = _seed_topic(config)
        (topic_dir / "t_Topic_Synthesis.md").write_text("---\n---\n\nOverview.\n", encoding="utf-8")
        console = MagicMock()
        monkeypatch.setattr(audit_mod, "console", console)

        audit_mod._act_orientation(config, ["t"], [], self._link_result(), "2026-06-21T00:00:00Z")

        assert (topic_dir / "AGENTS.md").exists()
        assert (config.library_dir / "AGENTS.md").exists()
        assert any(
            "Orientation files regenerated" in str(call) for call in console.print.call_args_list
        )

    def test_act_gaps_prints_discover_commands(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        console = MagicMock()
        monkeypatch.setattr(audit_mod, "console", console)
        reports = [_audit_report(topic="t", gaps=["Only 1 channel tracked."])]

        audit_mod._act_gaps(config, ["t"], reports, self._link_result(), "2026-06-21T00:00:00Z")

        joined = " ".join(str(call) for call in console.print.call_args_list)
        assert "distill discover --from-gaps --topic t --preview" in joined

    def test_act_stale_prints_reanalysis_commands(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        console = MagicMock()
        monkeypatch.setattr(audit_mod, "console", console)
        reports = [
            _audit_report(
                staleness=StalenessRollup(
                    stale=[
                        {
                            "insight": "papers/p1/p1_Insights.md",
                            "recorded": "paper-insight@1",
                            "current": "paper-insight@2",
                        }
                    ]
                )
            )
        ]

        audit_mod._act_stale(config, ["t"], reports, self._link_result(), "2026-06-21T00:00:00Z")

        joined = " ".join(str(call) for call in console.print.call_args_list)
        assert "papers/p1/p1_Insights.md" in joined
        assert "re-run its original ingest verb" in joined

    def test_act_freshness_prints_resynthesis_and_legacy_paths(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        topic_dir = _seed_topic(config)
        legacy = topic_dir / "legacy_Topic_Synthesis.md"
        legacy.write_text("old", encoding="utf-8")
        console = MagicMock()
        monkeypatch.setattr(audit_mod, "console", console)
        reports = [
            _audit_report(
                freshness=SynthesisFreshness(
                    stale=[{"synthesis": "t_Topic_Synthesis.md", "behind": 1, "gap_days": 3}],
                    shadowed_legacy=[{"active": "t_Topic_Synthesis.md", "legacy": legacy.name}],
                )
            )
        ]

        audit_mod._act_freshness(
            config, ["t"], reports, self._link_result(), "2026-06-21T00:00:00Z"
        )

        joined = " ".join(str(call) for call in console.print.call_args_list)
        assert "distill corpus t" in joined
        assert legacy.name in joined

    @pytest.mark.parametrize("choice", ["1", "2", "3", "4", "5"])
    def test_action_menu_dispatches_selected_handler(self, tmp_path, monkeypatch, choice):
        config = _config(tmp_path)
        topic_dir = _seed_topic(config)
        legacy = topic_dir / "legacy_Topic_Synthesis.md"
        legacy.write_text("old", encoding="utf-8")
        broken = BrokenLink(
            source_file=config.library_dir / "topics" / "t" / "note.md",
            line_number=1,
            link_text="[[missing]]",
            target_slug="missing",
        )
        reports = [
            _audit_report(
                broken_links=[broken],
                gaps=["Only 1 channel tracked."],
                staleness=StalenessRollup(
                    stale=[
                        {
                            "insight": "papers/p1/p1_Insights.md",
                            "recorded": "paper-insight@1",
                            "current": "paper-insight@2",
                        }
                    ]
                ),
                freshness=SynthesisFreshness(
                    stale=[{"synthesis": "t_Topic_Synthesis.md", "behind": 1, "gap_days": 3}],
                    shadowed_legacy=[{"active": "t_Topic_Synthesis.md", "legacy": legacy.name}],
                ),
            )
        ]
        handler = MagicMock()
        selected_key = {
            "1": "fix-links",
            "2": "orientation",
            "3": "gaps",
            "4": "stale",
            "5": "freshness",
        }[choice]
        monkeypatch.setitem(audit_mod._ACTIONS, selected_key, handler)
        monkeypatch.setattr(audit_mod, "tty_prompt", lambda *_a, **_k: choice)
        monkeypatch.setattr(audit_mod, "console", MagicMock())

        audit_mod._action_menu(
            config, ["t"], reports, self._link_result([broken]), "2026-06-21T00:00:00Z"
        )

        handler.assert_called_once()


class TestAuditCommand:
    def test_no_topics_console_message(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(audit_mod, "get_config", lambda: config)

        result = CliRunner().invoke(cli.app, ["audit", "all"])

        assert result.exit_code == 0
        assert "No topics found to audit" in result.output

    def test_global_json_audit_next_actions(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        monkeypatch.setattr(audit_mod, "get_config", lambda: config)

        result = CliRunner().invoke(cli.app, ["--json", "audit", "t", "--next-actions"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["schema_version"] == "next-actions.v1"
        assert "finding(s)" not in result.output

    def test_no_topics_next_actions_json(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(audit_mod, "get_config", lambda: config)

        result = CliRunner().invoke(cli.app, ["audit", "all", "--next-actions", "--json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["actions"] == []

    def test_audit_all_writes_library_audit(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        monkeypatch.setattr(audit_mod, "get_config", lambda: config)

        result = CliRunner().invoke(cli.app, ["audit", "all", "--report-only"])

        assert result.exit_code == 0
        assert (config.library_dir / "Library_Audit.md").exists()
        assert "Library:" in result.output

    def test_healthy_corpus_message(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        monkeypatch.setattr(audit_mod, "get_config", lambda: config)
        monkeypatch.setattr(
            audit_mod,
            "_build_report",
            lambda *_a, **_k: _audit_report(),
        )

        result = CliRunner().invoke(cli.app, ["audit", "t"])

        assert result.exit_code == 0
        assert "Corpus is healthy: no findings" in result.output

    def test_interactive_action_menu_when_findings(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        monkeypatch.setattr(audit_mod, "get_config", lambda: config)
        monkeypatch.setattr(audit_mod, "tty_prompt", lambda *_a, **_k: "q")
        monkeypatch.setattr(
            audit_mod,
            "_build_report",
            lambda *_a, **_k: _audit_report(gaps=["Only 1 channel tracked."]),
        )

        result = CliRunner().invoke(cli.app, ["audit", "t"])

        assert result.exit_code == 0
        assert "Actions" in result.output
        assert "Done" in result.output

    def test_next_actions_console_plan(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        monkeypatch.setattr(audit_mod, "get_config", lambda: config)
        monkeypatch.setattr(
            audit_mod,
            "_build_report",
            lambda *_a, **_k: _audit_report(gaps=["Only 1 channel tracked."]),
        )

        result = CliRunner().invoke(cli.app, ["audit", "t", "--next-actions"])

        assert result.exit_code == 0
        assert "Next actions" in result.output
        assert "discover --from-gaps" in result.output

    def test_register_adds_audit_command(self):
        import typer

        app = typer.Typer()
        audit_mod.register(app)
        assert any(cmd.name == "audit" for cmd in app.registered_commands)
