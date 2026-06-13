"""Tests for the self-update module and `distill update` command."""

from __future__ import annotations

import json
from unittest.mock import patch

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
                pass

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
