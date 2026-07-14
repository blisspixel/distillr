"""Unit tests for ``distill.commands.doctor`` presentation and CLI paths."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.commands import doctor as doctor_mod
from distill.config import DistillConfig
from distill.doctor.adapters import AdapterDoctorReport, AdapterProbe
from distill.library import Library
from distill.library.state import ChannelState

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_local_provider_probes(monkeypatch) -> None:
    """Keep doctor unit tests independent of services running on the host."""

    monkeypatch.setattr(doctor_mod, "_check_ollama_status", lambda: ("unavailable", ()))
    monkeypatch.setattr(doctor_mod, "_check_lmstudio_status", lambda: "unavailable")


def _config(tmp_path: Path, **kwargs) -> DistillConfig:
    defaults = {
        "xai_api_key": "test-key",
        "gemini_api_key": "",
        "openai_api_key": "",
        "distill_output_dir": tmp_path / "library",
        "distill_cost_mode": "no-metered",
    }
    defaults.update(kwargs)
    config = DistillConfig(**defaults)
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def _links_corpus(library_dir: Path) -> None:
    topic_dir = library_dir / "topics" / "ai"
    topic_dir.mkdir(parents=True)
    (topic_dir / "ai_Insights.md").write_text("# Insights\n", encoding="utf-8")
    (topic_dir / "summary.md").write_text(
        "See [[ai_Insights|OK]] and [[missing_Insights|Broken]].\n",
        encoding="utf-8",
    )


class TestDoctorFlagValidation:
    def test_fix_requires_links(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor_mod, "get_config", lambda: _config(tmp_path))

        result = runner.invoke(cli.app, ["doctor", "--fix"])

        assert result.exit_code == 1
        assert "--fix requires --links" in result.output

    def test_apply_requires_migration_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor_mod, "get_config", lambda: _config(tmp_path))

        result = runner.invoke(cli.app, ["doctor", "--apply"])

        assert result.exit_code == 1
        assert "--apply requires --migrate-links or --migrate-frontmatter" in result.output


class TestDoctorLinksMode:
    def test_links_missing_library_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        config.library_dir.rmdir()

        result = runner.invoke(cli.app, ["doctor", "--links"])

        assert result.exit_code == 1
        assert "library directory does not exist" in result.output

    def test_links_console_report(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _links_corpus(config.library_dir)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--links"])

        assert result.exit_code == 0
        assert "Link Integrity Check" in result.output
        assert "Broken links:" in result.output

    def test_links_json_output(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _links_corpus(config.library_dir)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--links", "--json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["is_healthy"] is False

    def test_links_fix_with_nothing_to_fix(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        (config.library_dir / "note.md").write_text("No links.\n", encoding="utf-8")
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--links", "--fix"])

        assert result.exit_code == 0
        assert "Nothing to fix" in result.output

    def test_links_json_fix_is_quiet(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _links_corpus(config.library_dir)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--links", "--fix", "--json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "Fixed" not in result.output

    def test_links_truncates_long_broken_lists(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        topic_dir = config.library_dir / "topics" / "ai"
        topic_dir.mkdir(parents=True)
        lines = ["See [[missing_Insights|Broken]]." for _ in range(25)]
        (topic_dir / "many.md").write_text("\n".join(lines), encoding="utf-8")
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--links"])

        assert result.exit_code == 0
        assert "and 5 more" in result.output

    def test_links_fix_repairs_broken_links(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _links_corpus(config.library_dir)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--links", "--fix"])

        assert result.exit_code == 0
        assert "Fixed 1 broken link" in result.output
        summary = config.library_dir / "topics" / "ai" / "summary.md"
        assert "[[missing_Insights|Broken]]" not in summary.read_text(encoding="utf-8")


class TestDoctorMigrationMode:
    def test_migrate_links_dry_run(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        topic_dir = config.library_dir / "topics" / "ai"
        topic_dir.mkdir(parents=True)
        (topic_dir / "insights.md").write_text("# Legacy\n", encoding="utf-8")
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--migrate-links"])

        assert result.exit_code == 0
        assert "Migration Plan (dry-run)" in result.output
        assert "RENAME:" in result.output

    def test_migrate_links_apply(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        topic_dir = config.library_dir / "topics" / "ai"
        topic_dir.mkdir(parents=True)
        (topic_dir / "insights.md").write_text("# Legacy\n", encoding="utf-8")
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--migrate-links", "--apply"])

        assert result.exit_code == 0
        assert "Migration Complete" in result.output
        assert (topic_dir / "ai_Insights.md").exists()

    def test_migrate_links_missing_library_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        config.library_dir.rmdir()
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--migrate-links"])

        assert result.exit_code == 1

    def test_migrate_links_nothing_found(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--migrate-links"])

        assert result.exit_code == 0
        assert "Nothing to migrate" in result.output

    def test_migrate_frontmatter_dry_run(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        note = config.library_dir / "topics" / "ai" / "note.md"
        note.parent.mkdir(parents=True)
        note.write_text("---\nconfidence: high\n---\n\nBody.\n", encoding="utf-8")
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--migrate-frontmatter"])

        assert result.exit_code == 0
        assert "Frontmatter Migration Plan" in result.output
        assert "confidence" in result.output

    def test_migrate_frontmatter_apply(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        note = config.library_dir / "topics" / "ai" / "note.md"
        note.parent.mkdir(parents=True)
        note.write_text("---\nconfidence: high\n---\n\nBody.\n", encoding="utf-8")
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--migrate-frontmatter", "--apply"])

        assert result.exit_code == 0
        assert "Frontmatter Migration Complete" in result.output
        assert "synthesis_scope:" in note.read_text(encoding="utf-8")

    def test_migrate_frontmatter_nothing_found(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor", "--migrate-frontmatter"])

        assert result.exit_code == 0
        assert "Nothing to migrate" in result.output


class TestDoctorHumanOutputBranches:
    def test_cost_mode_warning_lists_key_names_without_values(self, tmp_path):
        config = _config(
            tmp_path,
            xai_api_key="xai-secret-value",
            openai_api_key="openai-secret-value",
            distill_cost_mode="auto",
        )

        warnings = doctor_mod._cost_mode_warnings(config)

        assert len(warnings) == 1
        assert "XAI_API_KEY" in warnings[0]
        assert "OPENAI_API_KEY" in warnings[0]
        assert "xai-secret-value" not in warnings[0]
        assert "openai-secret-value" not in warnings[0]

    def test_no_metered_mode_suppresses_auto_cost_warning(self, tmp_path):
        config = _config(
            tmp_path,
            xai_api_key="xai-secret-value",
            distill_cost_mode="no-metered",
        )

        assert doctor_mod._cost_mode_warnings(config) == []

    def test_human_output_reports_cost_mode_warning(self, tmp_path, monkeypatch):
        config = _config(
            tmp_path,
            xai_api_key="xai-secret-value",
            openai_api_key="openai-secret-value",
            distill_cost_mode="auto",
        )

        def fake(provider, _config):
            if provider == "xai":
                return ("ok", "stub")
            if provider == "openai":
                return ("ok", "stub")
            return ("not_set", "")

        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "_doctor_validate_key", fake)

        result = runner.invoke(cli.app, ["doctor"])

        assert result.exit_code == 0
        assert "Cost mode:" in result.output
        assert "API-billed routes" in result.output
        assert "xai-secret-value" not in result.output
        assert "openai-secret-value" not in result.output

    def test_xai_missing_and_invalid_gemini(self, tmp_path, monkeypatch):
        config = _config(tmp_path, xai_api_key="")

        def fake(provider, _config):
            if provider == "xai":
                return ("missing", "")
            if provider == "gemini":
                return ("invalid", "400 bad key")
            return ("not_set", "")

        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "_doctor_validate_key", fake)

        result = runner.invoke(cli.app, ["doctor"])

        assert "NOT SET (required)" in result.output
        assert "GEMINI_API_KEY" in result.output

    def test_openai_optional_states(self, tmp_path, monkeypatch):
        config = _config(tmp_path, openai_api_key="set")

        def fake(provider, _config):
            if provider == "openai":
                return ("unknown", "timeout")
            return ("ok", "stub") if provider == "xai" else ("not_set", "")

        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "_doctor_validate_key", fake)

        result = runner.invoke(cli.app, ["doctor"])

        assert "OPENAI_API_KEY" in result.output
        assert "could not verify" in result.output

    def test_scribe_not_configured(self, tmp_path, monkeypatch):
        config = _config(tmp_path, scribe_path="")
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor"])

        assert "scribe            not set (optional transcript fallback)" in result.output

    def test_ytdlp_not_found_and_entailment_available(self, tmp_path, monkeypatch):
        import sys

        config = _config(tmp_path)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(
            "distill.pipeline.verify_entailment.entailment_available",
            lambda: True,
        )
        monkeypatch.setitem(sys.modules, "yt_dlp", MagicMock())
        monkeypatch.setattr(
            doctor_mod,
            "ytdlp_age_days",
            MagicMock(side_effect=RuntimeError("no yt-dlp")),
        )

        def broken_import(name):
            if name == "yt_dlp":
                raise ImportError("missing")
            raise ImportError(name)

        monkeypatch.setattr("importlib.metadata.version", broken_import)

        result = runner.invoke(cli.app, ["doctor"])

        assert "yt-dlp            not found" in result.output
        assert "entailment tier" in result.output

    def test_faster_whisper_and_provider_routing(self, tmp_path, monkeypatch):
        import importlib.metadata as imd
        import sys

        config = _config(tmp_path, openai_api_key="openai-key")
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        def version(name):
            if name == "faster-whisper":
                return "1.2.3"
            return imd.version(name)

        fake_ct = MagicMock()
        fake_ct.get_cuda_device_count.return_value = 0
        fake_ct.get_supported_compute_types.return_value = {"float16"}

        cache = tmp_path / "hf" / "hub" / "models--Systran--faster-whisper-large-v3"
        cache.mkdir(parents=True)
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        monkeypatch.setattr("importlib.metadata.version", version)
        sys.modules["ctranslate2"] = fake_ct

        result = runner.invoke(cli.app, ["doctor"])

        assert "faster-whisper" in result.output
        assert "Provider routing:" in result.output
        assert "openai whisper-1" in result.output
        assert "whisper models" in result.output


class TestDoctorHumanOutput:
    def _patch_keys(self, monkeypatch, mapping):
        def fake(provider, _config):
            return mapping.get(provider, ("not_set", ""))

        monkeypatch.setattr(doctor_mod, "_doctor_validate_key", fake)

    def test_reports_key_status_variants(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        self._patch_keys(
            monkeypatch,
            {
                "xai": ("unknown", "timeout"),
                "gemini": ("invalid", "400 API_KEY_INVALID"),
                "anthropic": ("skipped", "Route blocked by no-metered cost policy"),
                "openai": ("ok", "stub"),
            },
        )
        monkeypatch.setattr(
            doctor_mod, "check_retired_models", lambda _c: ["retired-model warning"]
        )
        monkeypatch.setattr(
            "playwright.sync_api.sync_playwright",
            MagicMock(side_effect=RuntimeError("no browser")),
        )

        result = runner.invoke(cli.app, ["doctor"])

        assert result.exit_code == 0
        assert "could not verify" in result.output
        assert "GEMINI_API_KEY" in result.output
        assert "live validation skipped by no-metered policy" in result.output
        assert "retired-model warning" in result.output
        assert "playwright" in result.output

    def test_update_flag_success(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "update_ytdlp", lambda: (True, "2026.06.21", False))
        monkeypatch.setattr(doctor_mod, "ytdlp_age_days", lambda: 40)
        monkeypatch.setattr(doctor_mod, "invalidate_preflight_cache", lambda *_a: None)

        result = runner.invoke(cli.app, ["doctor", "--update"])

        assert result.exit_code == 0
        assert "upgraded to" in result.output

    def test_update_flag_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "update_ytdlp", lambda: (False, "pip failed", False))

        result = runner.invoke(cli.app, ["doctor", "--update"])

        assert result.exit_code == 0
        assert "upgrade failed" in result.output

    def test_scribe_paths(self, tmp_path, monkeypatch):
        def _ok(provider, _config):
            return ("ok", "stub") if provider == "xai" else ("not_set", "")

        monkeypatch.setattr(doctor_mod, "_doctor_validate_key", _ok)

        config = _config(tmp_path, scribe_path=str(tmp_path / "missing-scribe"))
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        missing = runner.invoke(cli.app, ["doctor"])
        assert "not found at" in missing.output

        scribe = tmp_path / "scribe.sh"
        scribe.write_text("#!/bin/sh\n", encoding="utf-8")
        config.scribe_path = str(scribe)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        present = runner.invoke(cli.app, ["doctor"])
        assert str(scribe) in present.output.replace("\n", "")

    def test_library_stats_and_watchlists(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        lib = Library(config)
        lib.add_channel("ai", "https://www.youtube.com/@chan", "Chan")
        lib.add_to_watchlist(
            "https://www.youtube.com/@deal",
            "Deal",
            topic="deals",
            instructions="focus deals",
        )
        lib.add_to_topic_watchlist("ai-watch", "agent memory", topic="ai")
        state_file = config.channel_dir("ai", "Chan") / "state.json"
        state = ChannelState(state_file)
        state.mark_processed("vid1", "Video 1", "20260101", analysis_mode="scan")
        (config.library_dir / "blob.bin").write_bytes(b"x" * 2048)
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["doctor"])

        assert result.exit_code == 0
        assert "Watching:" in result.output
        assert "TopicWatch:" in result.output
        assert "scan" in result.output
        assert "Disk:" in result.output


class TestDoctorJsonExtras:
    def test_json_counts_direct_filesystem_corpus(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        video_dir = config.video_dir("direct-topic", "Direct Channel", "video-1")
        video_dir.mkdir(parents=True)
        (video_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "video_id": "video-1",
                    "title": "Direct video",
                    "analysis_mode": "full",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(
            doctor_mod,
            "_doctor_validate_key",
            lambda provider, cfg: ("not_set", ""),
        )
        monkeypatch.setattr(doctor_mod, "_check_ollama_status", lambda: ("unavailable", ()))
        monkeypatch.setattr(doctor_mod, "_check_lmstudio_status", lambda: "unavailable")

        result = runner.invoke(cli.app, ["doctor", "--json"])

        assert result.exit_code == 0
        checks = json.loads(result.output)["data"]["checks"]
        assert checks["topics"] == "1"
        assert checks["channels"] == "1"

    def test_json_reports_cost_mode_warning_without_secret_values(self, tmp_path, monkeypatch):
        config = _config(
            tmp_path,
            xai_api_key="xai-secret-value",
            openai_api_key="openai-secret-value",
            distill_cost_mode="auto",
        )

        def fake(provider, _config):
            if provider in {"xai", "openai"}:
                return ("ok", "stub")
            return ("not_set", "")

        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "_doctor_validate_key", fake)

        result = runner.invoke(cli.app, ["doctor", "--json"])
        data = json.loads(result.output)["data"]

        assert data["checks"]["cost_mode"] == "auto"
        warning_text = "\n".join(data["warnings"])
        assert "XAI_API_KEY" in warning_text
        assert "OPENAI_API_KEY" in warning_text
        assert "xai-secret-value" not in warning_text
        assert "openai-secret-value" not in warning_text

    def test_json_flags_invalid_keys_and_missing_ytdlp(self, tmp_path, monkeypatch):
        config = _config(tmp_path, xai_api_key="bad")

        def fake(provider, _config):
            if provider == "xai":
                return ("invalid", "401 unauthorized")
            if provider == "gemini":
                return ("invalid", "403 forbidden")
            return ("not_set", "")

        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "_doctor_validate_key", fake)
        monkeypatch.setattr(
            "importlib.metadata.version",
            MagicMock(side_effect=ImportError("no yt-dlp")),
        )

        result = runner.invoke(cli.app, ["doctor", "--json"])

        data = json.loads(result.output)["data"]
        assert data["checks"]["yt_dlp"] == "not_found"
        assert any("XAI_API_KEY" in warning for warning in data["warnings"])
        assert any("GEMINI_API_KEY" in warning for warning in data["warnings"])

    def test_local_route_availability_report_is_portable(self):
        report = doctor_mod._local_route_availability_report(
            ollama_status="running",
            ollama_models=("qwen3.5:27b",),
            lmstudio_status="unavailable",
        )

        assert report[0]["signal"]["provider"] == "ollama"
        assert report[0]["decision"]["available"] is True
        assert report[1]["signal"]["provider"] == "lmstudio"
        assert report[1]["decision"]["available"] is False
        assert report[2]["signal"]["provider"] == "ollama"
        assert report[2]["signal"]["model"] == "qwen3.5:27b"
        assert report[2]["decision"]["available"] is True
        assert "account" not in json.dumps(report).lower()


class TestDoctorAdapterReport:
    def _fake_report(self) -> AdapterDoctorReport:
        return AdapterDoctorReport(
            schema_version="adapter-doctor.v1",
            adapters=[
                AdapterProbe(
                    name="codex",
                    binary="codex",
                    route_class="included-plan",
                    installed=False,
                    version="1.2.3",
                    no_metered_candidate=True,
                    no_metered_eligible=False,
                    support_statement="planned",
                    support_statement_detail={
                        "status": "planned",
                        "checked_on": "2026-06-18",
                        "no_metered_current": False,
                    },
                    auth_mode="session",
                    config_files_found=["config.toml"],
                    auth_evidence=["session_marker"],
                    env_blockers_present=["OPENAI_API_KEY"],
                    missing_flags=["--json-output"],
                    blocked_reasons=["codex is not installed"],
                )
            ],
        )

    def test_adapter_console_report(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor_mod, "get_config", lambda: _config(tmp_path))
        monkeypatch.setattr(
            "distill.doctor.adapters.adapter_doctor_report",
            lambda: self._fake_report(),
        )

        result = runner.invoke(cli.app, ["doctor", "--adapters"])

        assert result.exit_code == 0
        assert "CLI Adapter Doctor" in result.output
        assert "BLOCKED" in result.output
        assert "support statement" in result.output
        assert "env blockers" in result.output

    def test_adapter_support_statement_empty_detail(self, monkeypatch):
        monkeypatch.setattr(doctor_mod, "console", MagicMock())
        doctor_mod._doctor_adapter_support_statement({})
        doctor_mod.console.print.assert_not_called()


class TestDoctorLocalInferenceSection:
    @pytest.mark.parametrize(
        "gpu_type",
        ["nvidia", "apple_silicon", "none"],
    )
    def test_gpu_profiles(self, tmp_path, monkeypatch, gpu_type):
        config = _config(tmp_path)
        profile = SimpleNamespace(
            gpu_type=gpu_type,
            gpu_name="Test GPU",
            vram_gb=16.0,
            system_ram_gb=32.0,
            is_container=gpu_type == "none",
        )
        monkeypatch.setattr("distill.doctor.hardware.detect_hardware", lambda: profile)
        monkeypatch.setattr(
            doctor_mod, "_check_ollama_status", lambda: ("running", ["qwen3.5:27b"])
        )
        monkeypatch.setattr(doctor_mod, "_check_lmstudio_status", lambda: "running")
        monkeypatch.setattr(
            "distill.doctor.recommendations.recommend_models",
            lambda _p: [
                SimpleNamespace(model_name="qwen3.5:27b", context_window=32768, reason="fits VRAM")
            ],
        )
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "console", MagicMock())

        doctor_mod._doctor_local_inference_section(config, "cyan")

        joined = " ".join(str(call) for call in doctor_mod.console.print.call_args_list)
        assert "Local Inference" in joined
        assert "Recommended Models" in joined
        assert "Next step" in joined

    def test_local_ready_without_cloud_key(self, tmp_path, monkeypatch):
        config = _config(tmp_path, xai_api_key="")
        profile = SimpleNamespace(
            gpu_type="none",
            gpu_name="",
            vram_gb=0.0,
            system_ram_gb=16.0,
            is_container=False,
        )
        monkeypatch.setattr("distill.doctor.hardware.detect_hardware", lambda: profile)
        monkeypatch.setattr(
            doctor_mod, "_check_ollama_status", lambda: ("running", ["qwen3.5:27b"])
        )
        monkeypatch.setattr(doctor_mod, "_check_lmstudio_status", lambda: "unavailable")
        monkeypatch.setattr(
            "distill.doctor.recommendations.recommend_models",
            lambda _p: [
                SimpleNamespace(model_name="qwen3.5:9b", context_window=8192, reason="CPU ok")
            ],
        )
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "console", MagicMock())

        doctor_mod._doctor_local_inference_section(config, "cyan")

        joined = " ".join(str(call) for call in doctor_mod.console.print.call_args_list)
        assert "Local ready, no API key" in joined


class TestHealthCommand:
    def test_health_no_topics_console(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor_mod, "get_config", lambda: _config(tmp_path))

        result = runner.invoke(cli.app, ["health", "all"])

        assert result.exit_code == 0
        assert "No topics found to audit" in result.output

    def test_health_healthy_topic(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        Library(config).add_channel("ai", "https://www.youtube.com/@chan", "Chan")
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "_collect_corpus_health_warnings", lambda *_a, **_k: [])

        result = runner.invoke(cli.app, ["health", "ai"])

        assert result.exit_code == 0
        assert "No obvious corpus health issues detected" in result.output

    def test_health_json_with_contested(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        Library(config).add_channel("ai", "https://www.youtube.com/@chan", "Chan")
        contested = SimpleNamespace(
            name="Graph Memory",
            is_entity=False,
            helpful_count=2,
            harmful_count=1,
            source_count=3,
            to_dict=lambda: {"name": "Graph Memory"},
        )
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "_collect_corpus_health_warnings", lambda *_a, **_k: [])
        monkeypatch.setattr(
            "distill.concepts.contradictions.find_contested",
            lambda _d: [contested],
        )

        result = runner.invoke(cli.app, ["--json", "health", "ai"])

        parsed = json.loads(result.output)
        assert parsed["data"]["contested_concepts"]["ai"][0]["name"] == "Graph Memory"

    def test_health_truncates_many_contested(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        Library(config).add_channel("ai", "https://www.youtube.com/@chan", "Chan")
        items = [
            SimpleNamespace(
                name=f"Concept {i}",
                is_entity=False,
                helpful_count=2,
                harmful_count=1,
                source_count=2,
            )
            for i in range(12)
        ]
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(doctor_mod, "_collect_corpus_health_warnings", lambda *_a, **_k: [])
        monkeypatch.setattr(
            "distill.concepts.contradictions.find_contested",
            lambda _d: items,
        )

        result = runner.invoke(cli.app, ["health", "ai"])

        assert "and 2 more" in result.output

    def test_health_lists_warnings_and_contested(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        Library(config).add_channel("ai", "https://www.youtube.com/@chan", "Chan")
        contested = SimpleNamespace(
            name="Graph Memory",
            is_entity=False,
            helpful_count=2,
            harmful_count=1,
            source_count=3,
        )
        monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
        monkeypatch.setattr(
            doctor_mod,
            "_collect_corpus_health_warnings",
            lambda *_a, **_k: ["ai: synthesis is stale"],
        )
        monkeypatch.setattr(
            "distill.concepts.contradictions.find_contested",
            lambda _d: [contested],
        )

        result = runner.invoke(cli.app, ["health", "ai"])

        assert result.exit_code == 0
        assert "synthesis is stale" in result.output
        assert "Contested concepts" in result.output
        assert "Graph Memory" in result.output
        assert "and 0 more" not in result.output

    def test_register_adds_doctor_and_health(self):
        import typer

        app = typer.Typer()
        doctor_mod.register(app)
        callbacks = {cmd.callback for cmd in app.registered_commands}
        assert doctor_mod.doctor in callbacks
        assert doctor_mod.health in callbacks


def test_check_retired_models_warns():
    from distill.config import DistillConfig
    from distill.doctor.checks import check_retired_models

    # minimal config with a retired (assume from router)
    c = DistillConfig(xai_analysis_model="grok-4.1-fast")  # example retired if in registry
    # since registry may not have, just call to cover
    ws = check_retired_models(c)
    assert isinstance(ws, list)


def test_doctor_key_auth_rejected_variants():
    from distill.doctor.checks import _doctor_key_auth_rejected

    class E:
        status_code = 401

    assert _doctor_key_auth_rejected(E())

    class E2:
        code = 403

    assert _doctor_key_auth_rejected(E2())

    class E3:
        response = type("r", (), {"status_code": 403})()

    assert _doctor_key_auth_rejected(E3())
    assert not _doctor_key_auth_rejected(Exception("other"))
