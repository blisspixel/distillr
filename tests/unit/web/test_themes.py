from __future__ import annotations

import stat
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from distill.web import theme, theme_install
from distill.web.server import create_app
from distill.web.theme_colors import color, contrast, distinct_statuses, mix, oklab, repair_contrast
from distill.web.theme_ui import appearance_controls, theme_metadata


def _custom(slug="custom"):
    return (
        (theme.BUILTIN_THEMES / "house-dark.toml")
        .read_text(encoding="utf-8")
        .replace('slug = "house-dark"', f'slug = "{slug}"')
    )


def _zip(files):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in files:
            archive.writestr(name, data)
    return stream.getvalue()


def test_every_shipped_theme_meets_contrast_and_distinct_status_contract():
    collection = theme.load_themes()
    assert len(collection.themes) == 12
    for palette in collection.themes:
        values = palette.colors
        for background in ("bg", "surface", "selection"):
            for role in ("text", "muted"):
                assert contrast(values[role], values[background]) >= 4.5, (
                    palette.slug,
                    role,
                    background,
                )
        for background in ("bg", "surface"):
            for role in ("accent", "success", "warning", "error", "info"):
                assert contrast(values[role], values[background]) >= 4.5
            for role in ("focus", "border"):
                assert contrast(values[role], values[background]) >= 3
        assert distinct_statuses(values["success"], values["error"])
        assert palette.slug in theme.theme_css(collection)


@pytest.mark.parametrize("value", ["red", "#fff", "#ffffff;url(x)", 1, None, "#gggggg"])
def test_strict_colors(value):
    with pytest.raises(ValueError):
        color(value)


@pytest.mark.parametrize(
    "slug", ["../outside", ".hidden", "x/y", "UPPER", "two words", "x" * 65, ".."]
)
def test_confined_ascii_slugs(slug):
    with pytest.raises(ValueError):
        theme.validate_slug(slug)


@pytest.mark.parametrize(
    "content",
    [
        "x" * (theme.THEME_MAX_BYTES + 1),
        'name = "unterminated',
        _custom() + '\n[script]\ncode="alert(1)"',
        _custom().replace('variant = "dark"', 'variant = "other"'),
        _custom().replace('text = "#ece6da"', 'text = "#16181d"'),
        _custom().replace('success = "#8cc58a"', 'success = "#ee8a7f"'),
        _custom().replace('text = "#ece6da"', 'text = "red"'),
        _custom().replace("[colors]", "[other]"),
        _custom().replace('focus = "#f59e0b"', 'untrusted = "#ffffff"'),
    ],
)
def test_invalid_theme_is_refused_before_any_install(content):
    with pytest.raises(ValueError):
        theme_install.install_theme_data(content)
    assert not (theme.user_themes_dir() / "custom.toml").exists()


def test_numeric_contrast_reference_values_and_lightness_repair():
    assert contrast("#000000", "#ffffff") == 21
    assert contrast("#777777", "#777777") == 1
    assert mix("#000000", "#ffffff", 0.5) == "#808080"
    assert oklab("#ffffff")[0] == pytest.approx(1, abs=0.00001)
    repaired = repair_contrast("#555555", ("#16181d", "#1d2027"), 4.5)
    assert contrast(repaired, "#1d2027") >= 4.5
    assert not distinct_statuses("#cccccc", "#cccccc")
    with pytest.raises(ValueError, match="cannot be repaired"):
        repair_contrast("#777777", ("#000000", "#ffffff"), 10)


def test_theme_repair_is_reported_and_input_is_immutable():
    parsed = theme.parse_theme(_custom().replace('accent = "#2dd4bf"', 'accent = "#555555"'))
    assert any("accent:" in repair for repair in parsed.repairs)
    with pytest.raises(TypeError):
        parsed.colors["text"] = "#000000"


def test_local_install_reload_and_remove_preserve_builtins(tmp_path):
    source = tmp_path / "custom.toml"
    source.write_text(_custom(), encoding="utf-8")
    report = theme_install.install_theme(str(source))
    assert report.installed == ("custom",)
    assert "custom" in {item.slug for item in theme.load_themes().themes}
    with pytest.raises(ValueError, match="already exists"):
        theme_install.install_theme(str(source))
    theme_install.remove_theme("custom")
    assert "custom" not in {item.slug for item in theme.load_themes().themes}
    with pytest.raises(ValueError, match="built-in"):
        theme_install.remove_theme("house-dark")
    with pytest.raises(ValueError):
        theme_install.remove_theme("custom")
    with pytest.raises(ValueError, match="built-in"):
        theme_install.install_theme_data(_custom("house-dark"))


def test_bad_dropped_theme_does_not_replace_current_theme():
    root = theme.user_themes_dir()
    root.mkdir(parents=True)
    (root / "invalid.toml").write_text("not valid TOML", encoding="utf-8")
    (root / "mismatch.toml").write_text(_custom("different"), encoding="utf-8")
    collection = theme.load_themes()
    assert len(collection.themes) == 12
    assert len(collection.notices) == 2
    assert "house-dark" in theme.theme_css(collection)


def test_archive_reads_only_bounded_non_executable_theme_data():
    symlink = zipfile.ZipInfo("repo/linked.toml")
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    files, ignored = theme_install._archive_themes(
        _zip(
            [
                ("repo/", ""),
                ("repo/custom.toml", _custom()),
                ("repo/evil.js", "throw 1"),
                (symlink, "../../outside"),
            ]
        )
    )
    assert set(files) == {"custom"}
    assert set(ignored) == {"repo/evil.js", "repo/linked.toml"}


@pytest.mark.parametrize(
    "files",
    [
        [("../escape.toml", _custom())],
        [("/absolute.toml", _custom())],
        [("repo/large.toml", " " * (theme.THEME_MAX_BYTES + 1))],
        [("repo/a.toml", _custom()), ("repo/b.toml", _custom())],
        [("repo/README.md", "no themes")],
    ],
)
def test_bad_archives_are_refused(files):
    with pytest.raises(ValueError):
        theme_install._archive_themes(_zip(files))


def test_raw_windows_separator_in_archive_is_refused():
    payload = _zip([("repo/bad.toml", _custom())]).replace(b"repo/bad.toml", b"repo\\bad.toml")
    with pytest.raises(ValueError, match="unsafe path"):
        theme_install._archive_themes(payload)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/o/r",
        "https://localhost/o/r",
        "https://github.com/o/r?x=y",
        "https://github.com/o/r#fragment",
        "https://github.com/o/r/extra",
        "https://user@github.com/o/r",
        "https://github.com/o/r\n",
    ],
)
def test_repository_urls_are_structurally_confined(url):
    with pytest.raises(ValueError):
        theme_install._github_repo(url)


def test_repository_install_and_update_use_hardened_fetch(monkeypatch):
    calls = []
    data = [_custom(), _custom().replace('name = "House Dark"', 'name = "Updated"')]

    def fetch(url, **kwargs):
        calls.append(url)
        return BytesIO(_zip([("repo/custom.toml", data.pop(0))]))

    monkeypatch.setattr(theme_install, "safe_urlopen", fetch)
    theme_install.install_theme("https://github.com/example/distill-custom-theme.git")
    assert theme_install.update_themes()[0].installed == ("custom",)
    assert len(calls) == 2 and calls[0].endswith("/archive/HEAD.zip")
    assert (
        next(item for item in theme.load_themes().themes if item.slug == "custom").name == "Updated"
    )


@pytest.mark.parametrize(
    "archive,reason",
    [
        (b"x" * (8 * 1024 * 1024 + 1), "8 MB"),
        (_zip([(f"repo/{index}.txt", "") for index in range(2001)]), "too many entries"),
        (_zip([("repo/a.toml", _custom()), ("repo/b.toml", _custom())]), "duplicate"),
        (_zip([("repo/a.toml", "x" * (theme.THEME_MAX_BYTES + 1))]), "16 KB"),
    ],
    ids=["archive-size", "entry-count", "duplicate-slug", "theme-size"],
)
def test_repository_limits_refuse_before_any_theme_is_published(monkeypatch, archive, reason):
    monkeypatch.setattr(theme_install, "safe_urlopen", lambda *a, **k: BytesIO(archive))
    with pytest.raises(ValueError, match=reason):
        theme_install.install_theme("https://github.com/example/theme")
    assert not (theme.user_themes_dir() / "custom.toml").exists()


def test_failed_batch_publication_removes_new_files_and_keeps_prior_palette(monkeypatch):
    theme_install.install_theme_data(_custom())
    previous = (theme.user_themes_dir() / "custom.toml").read_bytes()
    real_write = theme_install.atomic_write_confined_text

    def fail_registry(path, text, root, **kwargs):
        if path.name == ".sources.json":
            raise OSError("disk full")
        return real_write(path, text, root, **kwargs)

    monkeypatch.setattr(theme_install, "atomic_write_confined_text", fail_registry)
    with pytest.raises(OSError, match="disk full"):
        theme_install._publish({"custom": _custom(), "new": _custom("new")}, source="", update=True)
    assert (theme.user_themes_dir() / "custom.toml").read_bytes() == previous
    assert not (theme.user_themes_dir() / "new.toml").exists()


def test_failed_publication_restores_prior_theme(monkeypatch):
    theme_install.install_theme_data(_custom())
    original = (theme.user_themes_dir() / "custom.toml").read_text(encoding="utf-8")
    real_write = theme_install.atomic_write_confined_text

    def fail_registry(path, text, root, **kwargs):
        if path.name == ".sources.json":
            raise OSError("disk full")
        return real_write(path, text, root, **kwargs)

    monkeypatch.setattr(theme_install, "atomic_write_confined_text", fail_registry)
    with pytest.raises(OSError):
        theme_install.install_theme_data(
            _custom().replace('name = "House Dark"', 'name = "Changed"'), update=True
        )
    assert (theme.user_themes_dir() / "custom.toml").read_text(encoding="utf-8") == original
    with pytest.raises(OSError):
        theme_install.remove_theme("custom")
    assert (theme.user_themes_dir() / "custom.toml").read_text(encoding="utf-8") == original


def test_theme_text_cannot_escape_markup_or_metadata():
    parsed = theme.parse_theme(
        _custom().replace('name = "House Dark"', 'name = "<script>alert(1)</script>"')
    )
    collection = theme.ThemeCollection((parsed,))
    assert "<script>alert" not in appearance_controls(collection)
    assert "<script>alert" not in theme_metadata(collection)


def test_live_theme_endpoints_keep_csp_and_require_import_authority(config):
    app = create_app(config)
    client = TestClient(app, base_url="http://localhost")
    page = client.get("/")
    assert 'data-theme="house-dark"' in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert (
        "unsafe-inline"
        not in page.headers["content-security-policy"].split("script-src")[1].split(";")[0]
    )
    response = client.get("/themes")
    assert len(response.json()["themes"]) == 12
    assert client.get("/themes.css").text == theme.theme_css()
    assert client.post("/themes/import", json={"content": _custom()}).status_code == 403
    headers = {"x-distill-theme-token": app.state.theme_token, "origin": "http://localhost"}
    assert (
        client.post(
            "/themes/import",
            json={"content": _custom()},
            headers={**headers, "origin": "http://evil.test"},
        ).status_code
        == 403
    )
    assert (
        client.post("/themes/import", json={"content": "bad TOML"}, headers=headers).status_code
        == 422
    )
    assert (
        client.post("/themes/import", json={"content": _custom()}, headers=headers).status_code
        == 200
    )
    assert len(client.get("/themes").json()["themes"]) == 13
    assert client.post("/themes/import", content=" " * 100000, headers=headers).status_code == 413
    assert client.post("/themes/import", json=["bad"], headers=headers).status_code == 422
