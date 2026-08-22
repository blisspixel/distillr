"""Tests for the default-library-location heuristic (downstream-reported misfire).

A stray ``pyproject.toml`` in ``site-packages`` made an installed distillr
claim "source checkout" and put the user's whole library inside
``site-packages\\library`` -- the exact bad home the docstring warns about.
"""

from __future__ import annotations

from pathlib import Path

from distill.config import _default_library_dir

_DISTILLR_PYPROJECT = '[project]\nname = "distillr"\nversion = "0.0.0"\n'


def _pkg(parent: Path) -> Path:
    """Simulate the installed/checked-out ``distill`` package directory."""
    pkg = parent / "distill"
    pkg.mkdir(parents=True, exist_ok=True)
    return pkg


def test_source_checkout_uses_repo_library(tmp_path: Path):
    repo = tmp_path / "distillr-repo"
    pkg = _pkg(repo)
    (repo / "pyproject.toml").write_text(_DISTILLR_PYPROJECT, encoding="utf-8")

    assert _default_library_dir(pkg) == repo / "library"


def test_stray_pyproject_in_site_packages_goes_home(tmp_path: Path):
    """The reported misfire: site-packages containing someone's pyproject.toml."""
    site = tmp_path / "Lib" / "site-packages"
    pkg = _pkg(site)
    (site / "pyproject.toml").write_text(_DISTILLR_PYPROJECT, encoding="utf-8")

    result = _default_library_dir(pkg)
    assert result == Path.home() / ".distill" / "library"
    assert "site-packages" not in result.parts


def test_foreign_pyproject_outside_site_packages_goes_home(tmp_path: Path):
    """A pyproject that is not distillr's own does not claim checkout status."""
    somewhere = tmp_path / "vendored"
    pkg = _pkg(somewhere)
    (somewhere / "pyproject.toml").write_text('[project]\nname = "othertool"\n', encoding="utf-8")

    assert _default_library_dir(pkg) == Path.home() / ".distill" / "library"


def test_no_marker_goes_home(tmp_path: Path):
    pkg = _pkg(tmp_path / "plain")
    assert _default_library_dir(pkg) == Path.home() / ".distill" / "library"


def test_unreadable_marker_goes_home(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    pkg = _pkg(repo)
    marker = repo / "pyproject.toml"
    marker.write_text(_DISTILLR_PYPROJECT, encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    original = Path.read_text

    def boom(self, *args, **kwargs):
        if self == marker:
            raise OSError("permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", boom)
    assert _default_library_dir(pkg) == tmp_path / "home" / ".distill" / "library"


def test_dist_packages_also_guarded(tmp_path: Path):
    dist = tmp_path / "lib" / "python3" / "dist-packages"
    pkg = _pkg(dist)
    (dist / "pyproject.toml").write_text(_DISTILLR_PYPROJECT, encoding="utf-8")

    assert _default_library_dir(pkg) == Path.home() / ".distill" / "library"
