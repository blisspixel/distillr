"""Tests for the self-update module and `distill update` command."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from distill import update as upd
from distill.cli import app

runner = CliRunner()


class TestVersionCompare:
    def test_latest_newer(self):
        assert upd.latest_is_newer("0.13.2", "0.14.0") is True

    def test_latest_same_or_older(self):
        assert upd.latest_is_newer("0.14.0", "0.14.0") is False
        assert upd.latest_is_newer("0.14.0", "0.13.9") is False

    def test_missing_or_unparseable(self):
        assert upd.latest_is_newer(None, "0.14.0") is False
        assert upd.latest_is_newer("0.14.0", None) is False
        assert upd.latest_is_newer("0.14.0", "not-a-version") is False

    def test_swallows_packaging_errors(self):
        with patch(
            "packaging.version.Version",
            side_effect=ImportError("blocked"),
        ):
            assert upd.latest_is_newer("0.13.0", "0.14.0") is False


class TestInstallMethod:
    def test_editable_is_source(self):
        with patch("distill.update._editable_install", return_value=True):
            assert upd.detect_install_method() == upd.METHOD_SOURCE

    def test_pipx_prefix(self, monkeypatch):
        monkeypatch.setattr(upd, "_editable_install", lambda: False)
        monkeypatch.setattr(upd.sys, "prefix", "/home/u/.local/pipx/venvs/distillr")
        assert upd.detect_install_method() == upd.METHOD_PIPX

    def test_uv_prefix(self, monkeypatch):
        monkeypatch.setattr(upd, "_editable_install", lambda: False)
        monkeypatch.setattr(upd.sys, "prefix", "/home/u/.local/share/uv/tools/distillr")
        assert upd.detect_install_method() == upd.METHOD_UV

    def test_plain_pip_default(self, monkeypatch):
        monkeypatch.setattr(upd, "_editable_install", lambda: False)
        monkeypatch.setattr(upd.sys, "prefix", "/usr")
        assert upd.detect_install_method() == upd.METHOD_PIP


class TestUpgradeCommand:
    def test_per_method(self):
        assert upd.upgrade_command(upd.METHOD_UV) == ["uv", "tool", "upgrade", "distillr"]
        assert upd.upgrade_command(upd.METHOD_PIPX) == ["pipx", "upgrade", "distillr"]
        assert upd.upgrade_command(upd.METHOD_PIP)[-3:] == ["install", "--upgrade", "distillr"]
        assert upd.upgrade_command(upd.METHOD_SOURCE) is None


class TestCheckForUpdate:
    def test_notice_when_newer(self, monkeypatch):
        printed = []
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "latest_version_cached", lambda *a, **k: "0.14.0")

        class C:
            def print(self, msg):
                printed.append(msg)

        upd.check_for_update(C(), None)
        assert any("0.14.0 is available" in m for m in printed)

    def test_silent_when_current(self, monkeypatch):
        printed = []
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.14.0")
        monkeypatch.setattr(upd, "latest_version_cached", lambda *a, **k: "0.14.0")

        class C:
            def print(self, msg):
                printed.append(msg)

        upd.check_for_update(C(), None)
        assert printed == []

    def test_opt_out(self, monkeypatch):
        monkeypatch.setenv("DISTILL_NO_UPDATE_CHECK", "1")
        called = {"net": False}
        monkeypatch.setattr(
            upd, "latest_version_cached", lambda *a, **k: called.__setitem__("net", True)
        )

        class C:
            def print(self, msg):
                return None

        upd.check_for_update(C(), None)
        assert called["net"] is False  # opt-out short-circuits before any network


class TestUpdateCommand:
    def test_check_json(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_UV)

        res = runner.invoke(app, ["--json", "update", "--check"])
        assert res.exit_code == 0
        data = json.loads(res.stdout)["data"]
        assert data["update_available"] is True
        assert data["install_method"] == "uv"

    def test_source_install_does_not_upgrade(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.14.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.15.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_SOURCE)
        ran = {"upgrade": False}
        monkeypatch.setattr(
            upd,
            "run_self_update",
            lambda *a, **k: ran.__setitem__("upgrade", True) or (True, "", False),
        )

        res = runner.invoke(app, ["update"])
        assert res.exit_code == 0
        assert ran["upgrade"] is False  # source checkout is never auto-upgraded
        assert "git pull" in res.stdout

    def test_upgrade_runs_when_newer(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)
        monkeypatch.setattr(upd, "run_self_update", lambda *a, **k: (True, "0.14.0", False))

        res = runner.invoke(app, ["update"])
        assert res.exit_code == 0
        assert "Updated to 0.14.0" in res.stdout

    def test_check_human_mode_when_newer(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)

        res = runner.invoke(app, ["update", "--check"])

        assert res.exit_code == 0
        assert "Update available" in res.stdout

    def test_check_human_mode_when_current(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.14.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)

        res = runner.invoke(app, ["update", "--check"])

        assert res.exit_code == 0
        assert "latest release" in res.stdout

    def test_already_latest_skips_upgrade(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.14.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)
        monkeypatch.setattr(
            upd,
            "run_self_update",
            lambda *a, **k: pytest.fail("upgrade should not run"),
        )

        res = runner.invoke(app, ["update"])

        assert res.exit_code == 0
        assert "Already on the latest release" in res.stdout

    def test_upgrade_noop_reports_already_at_latest(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)
        monkeypatch.setattr(upd, "run_self_update", lambda *a, **k: (True, "0.13.0", True))

        res = runner.invoke(app, ["update"])

        assert res.exit_code == 0
        assert "Already at the latest release" in res.stdout

    def test_upgrade_failure_exits(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)
        monkeypatch.setattr(upd, "run_self_update", lambda *a, **k: (False, "pip broke", False))

        res = runner.invoke(app, ["update"])

        assert res.exit_code == 1
        assert "Update failed" in res.stdout

    def test_source_install_json(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.14.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.15.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_SOURCE)

        res = runner.invoke(app, ["--json", "update"])

        assert res.exit_code == 0
        data = json.loads(res.stdout)["data"]
        assert "git pull" in data["message"]

    def test_already_latest_json(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.14.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)

        res = runner.invoke(app, ["--json", "update"])

        assert res.exit_code == 0
        data = json.loads(res.stdout)["data"]
        assert data["reason"] == "already-latest"

    def test_upgrade_success_json(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)
        monkeypatch.setattr(upd, "run_self_update", lambda *a, **k: (True, "0.14.0", False))

        res = runner.invoke(app, ["--json", "update"])

        assert res.exit_code == 0
        data = json.loads(res.stdout)["data"]
        assert data["upgraded"] is True
        assert data["new_version"] == "0.14.0"

    def test_upgrade_failure_json_exits(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "fetch_latest_version", lambda *a, **k: "0.14.0")
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)
        monkeypatch.setattr(upd, "run_self_update", lambda *a, **k: (False, "pip broke", False))

        res = runner.invoke(app, ["--json", "update"])

        assert res.exit_code == 1
        data = json.loads(res.stdout)["data"]
        assert data["error"] == "pip broke"


class TestInstalledVersion:
    def test_reads_distillr_metadata(self, monkeypatch):
        monkeypatch.setattr(
            upd.importlib.metadata,
            "version",
            lambda name: "1.2.3" if name == upd.PACKAGE else pytest.fail("unexpected"),
        )
        assert upd.get_installed_version() == "1.2.3"

    def test_falls_back_to_distill_name(self, monkeypatch):
        def fake_version(name):
            if name == upd.PACKAGE:
                raise Exception("missing")
            if name == "distill":
                return "0.9.0"
            raise Exception("unexpected")

        monkeypatch.setattr(upd.importlib.metadata, "version", fake_version)
        assert upd.get_installed_version() == "0.9.0"

    def test_returns_none_when_undetected(self, monkeypatch):
        monkeypatch.setattr(
            upd.importlib.metadata, "version", lambda _name: (_ for _ in ()).throw(Exception())
        )
        assert upd.get_installed_version() is None


class TestFetchLatestVersion:
    def test_returns_pypi_version(self):
        response = MagicMock()
        response.json.return_value = {"info": {"version": "0.15.0"}}
        with patch("requests.get", return_value=response):
            assert upd.fetch_latest_version() == "0.15.0"

    def test_swallows_network_errors(self):
        with patch("requests.get", side_effect=OSError("offline")):
            assert upd.fetch_latest_version() is None

    def test_rejects_non_string_version(self):
        response = MagicMock()
        response.json.return_value = {"info": {"version": 123}}
        with patch("requests.get", return_value=response):
            assert upd.fetch_latest_version() is None


class TestEditableInstall:
    def test_detects_editable_direct_url(self, monkeypatch):
        dist = MagicMock()
        dist.read_text.return_value = json.dumps({"dir_info": {"editable": True}})
        monkeypatch.setattr(upd.importlib.metadata, "distribution", lambda _name: dist)
        assert upd._editable_install() is True

    def test_returns_false_without_metadata(self, monkeypatch):
        monkeypatch.setattr(
            upd.importlib.metadata, "distribution", MagicMock(side_effect=Exception("missing"))
        )
        assert upd._editable_install() is False


class TestRunSelfUpdate:
    def test_source_install_returns_guidance(self, monkeypatch):
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_SOURCE)
        ok, detail, noop = upd.run_self_update()
        assert ok is False
        assert "git pull" in detail
        assert noop is False

    def test_upgrade_success(self, monkeypatch):
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_UV)
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "_safe_subprocess_env", lambda: ("/safe", {"PYTHONSAFEPATH": "1"}))
        monkeypatch.setattr(upd, "resolve_executable", lambda name: "/trusted/uv")
        result = MagicMock(returncode=0, stdout="", stderr="")
        run = MagicMock(return_value=result)
        monkeypatch.setattr(upd.subprocess, "run", run)

        ok, detail, noop = upd.run_self_update()

        assert ok is True
        assert detail == "0.13.0"
        assert noop is True
        assert run.call_args.args[0] == ["/trusted/uv", "tool", "upgrade", "distillr"]

    def test_upgrade_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "_safe_subprocess_env", lambda: ("/safe", {}))
        result = MagicMock(returncode=1, stdout="", stderr="permission denied")
        monkeypatch.setattr(upd.subprocess, "run", lambda *a, **k: result)

        ok, detail, noop = upd.run_self_update()

        assert ok is False
        assert "permission denied" in detail
        assert noop is False

    def test_upgrade_command_not_found(self, monkeypatch):
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_UV)
        monkeypatch.setattr(upd, "_safe_subprocess_env", lambda: ("/safe", {}))
        monkeypatch.setattr(upd, "resolve_executable", lambda name: None)
        run = MagicMock()
        monkeypatch.setattr(upd.subprocess, "run", run)

        ok, detail, _noop = upd.run_self_update()

        assert ok is False
        assert "not found on PATH" in detail
        run.assert_not_called()

    def test_upgrade_generic_exception(self, monkeypatch):
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)
        monkeypatch.setattr(upd, "_safe_subprocess_env", lambda: ("/safe", {}))
        monkeypatch.setattr(upd.subprocess, "run", MagicMock(side_effect=RuntimeError("boom")))

        ok, detail, _noop = upd.run_self_update()

        assert ok is False
        assert detail == "boom"

    def test_upgrade_timeout(self, monkeypatch):
        monkeypatch.setattr(upd, "detect_install_method", lambda: upd.METHOD_PIP)
        monkeypatch.setattr(upd, "_safe_subprocess_env", lambda: ("/safe", {}))
        monkeypatch.setattr(
            upd.subprocess,
            "run",
            MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["pip"], timeout=300)),
        )

        ok, detail, _noop = upd.run_self_update()

        assert ok is False
        assert "timed out" in detail

    def test_safe_subprocess_env_strips_python_injection(self, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", "/evil")
        monkeypatch.setenv("PYTHONHOME", "/evil")
        monkeypatch.setenv("XAI_API_KEY", "secret")
        cwd, env = upd._safe_subprocess_env()
        assert "PYTHONPATH" not in env
        assert "PYTHONHOME" not in env
        assert "XAI_API_KEY" not in env
        assert env["PYTHONSAFEPATH"] == "1"
        assert cwd


class TestUpdateCache:
    def test_latest_version_cached_uses_fresh_entry(self, tmp_path, monkeypatch):
        library = tmp_path / "library"
        cache_file = library / ".distill" / upd.UPDATE_CACHE_NAME
        cache_file.parent.mkdir(parents=True)
        now = datetime(2026, 6, 21, 12, 0, 0)
        cache_file.write_text(
            json.dumps(
                {
                    upd.PACKAGE: {
                        "latest": "0.16.0",
                        "checked_at": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
                    }
                }
            ),
            encoding="utf-8",
        )
        fetch = MagicMock()
        monkeypatch.setattr(upd, "fetch_latest_version", fetch)

        latest = upd.latest_version_cached(library, now=now)

        assert latest == "0.16.0"
        fetch.assert_not_called()

    def test_latest_version_cached_fetches_when_stale(self, tmp_path, monkeypatch):
        library = tmp_path / "library"
        cache_file = library / ".distill" / upd.UPDATE_CACHE_NAME
        cache_file.parent.mkdir(parents=True)
        now = datetime(2026, 6, 21, 12, 0, 0)
        cache_file.write_text(
            json.dumps(
                {
                    upd.PACKAGE: {
                        "latest": "0.15.0",
                        "checked_at": (now - timedelta(hours=30)).isoformat(timespec="seconds"),
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(upd, "fetch_latest_version", lambda: "0.16.0")

        latest = upd.latest_version_cached(library, now=now)

        assert latest == "0.16.0"
        saved = json.loads(cache_file.read_text(encoding="utf-8"))
        assert saved[upd.PACKAGE]["latest"] == "0.16.0"

    def test_cache_helpers_noop_without_path(self):
        assert upd._cache_path(None) is None
        assert upd._read_cache(None) == {}
        upd._write_cache(None, {"distillr": {}})

    def test_read_cache_handles_invalid_json(self, tmp_path):
        cache_file = tmp_path / "bad.json"
        cache_file.write_text("not-json", encoding="utf-8")
        assert upd._read_cache(cache_file) == {}

    def test_write_cache_replaces_symlink_without_overwriting_target(self, tmp_path):
        target = tmp_path / "operator-notes.txt"
        target.write_text("preserve me", encoding="utf-8")
        cache_file = tmp_path / "cache.json"
        try:
            cache_file.symlink_to(target)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        upd._write_cache(cache_file, {upd.PACKAGE: {"latest": "1.2.3"}})

        assert target.read_text(encoding="utf-8") == "preserve me"
        assert not cache_file.is_symlink()
        assert json.loads(cache_file.read_text(encoding="utf-8"))[upd.PACKAGE]["latest"] == "1.2.3"

    def test_is_fresh_rejects_bad_timestamp(self):
        now = datetime(2026, 6, 21, 12, 0, 0)
        assert upd._is_fresh({"checked_at": "not-a-date"}, now) is False
        assert upd._is_fresh({}, now) is False


class TestCheckForUpdateEdgeCases:
    def test_skips_dev_builds(self, monkeypatch):
        printed = []
        monkeypatch.setattr(upd, "get_installed_version", lambda: "dev")
        monkeypatch.setattr(
            upd,
            "latest_version_cached",
            lambda *a, **k: pytest.fail("should not fetch"),
        )

        class C:
            def print(self, msg):
                printed.append(msg)

        upd.check_for_update(C(), None)
        assert printed == []

    def test_skips_when_version_undetected(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: None)
        monkeypatch.setattr(
            upd,
            "latest_version_cached",
            lambda *a, **k: pytest.fail("should not fetch"),
        )

        class C:
            def print(self, msg):
                return None

        upd.check_for_update(C(), None)

    def test_swallows_console_print_errors(self, monkeypatch):
        monkeypatch.setattr(upd, "get_installed_version", lambda: "0.13.0")
        monkeypatch.setattr(upd, "latest_version_cached", lambda *a, **k: "0.14.0")

        class C:
            def print(self, msg):
                raise RuntimeError("console broken")

        upd.check_for_update(C(), None)
