# pyright: strict
"""Install bounded theme data from local files or public GitHub archives."""

from __future__ import annotations

import json
import re
import stat
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import urlsplit

from distill.ingestors.net import safe_urlopen
from distill.library.confined import read_confined_text
from distill.library.confined_state import (
    atomic_write_confined_text,
    confined_file_identity,
    read_confined_state_text,
    unlink_confined_file,
)
from distill.library.locking import exclusive_path_lock
from distill.parsing import strict_json_loads
from distill.web.theme import (
    BUILTIN_THEMES,
    THEME_MAX_BYTES,
    load_themes,
    parse_theme,
    user_themes_dir,
    validate_slug,
)

_ARCHIVE_MAX = 8 * 1024 * 1024
_MAX_THEMES = 20


@dataclass(frozen=True)
class ThemeInstallReport:
    installed: tuple[str, ...]
    ignored: tuple[str, ...] = ()


def _github_repo(url: str) -> tuple[str, str]:
    if len(url) > 2048 or any(ord(c) < 32 for c in url):
        raise ValueError("invalid public GitHub repository URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
        raise ValueError("theme repositories require an HTTPS github.com owner/repo URL")
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if len(parts) != 2 or any(
        re.fullmatch(r"[A-Za-z0-9_\-][A-Za-z0-9_.\-]*", part, re.ASCII) is None for part in parts
    ):
        raise ValueError("invalid public GitHub repository identity")
    return parts[0], parts[1]


def _sources(root: Path) -> dict[str, str]:
    text = (
        read_confined_state_text(root / ".sources.json", root, max_bytes=64 * 1024)
        if root.exists()
        else None
    )
    if text is None:
        return {}
    raw: object = strict_json_loads(text)
    if not isinstance(raw, dict):
        raise ValueError("invalid theme source registry")
    result: dict[str, str] = {}
    for key, value in cast(dict[object, object], raw).items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("invalid theme source registry entry")
        validate_slug(key)
        if value:
            _github_repo(value)
        result[key] = value
    return result


def _read_archive_theme(archive: zipfile.ZipFile, entry: zipfile.ZipInfo) -> tuple[str, str]:
    if entry.file_size > THEME_MAX_BYTES:
        raise ValueError("theme file exceeds the 16 KB limit")
    with archive.open(entry) as stream:
        data = stream.read(THEME_MAX_BYTES + 1)
    text = data.decode("utf-8")
    return parse_theme(text).slug, text


def _archive_themes(payload: bytes) -> tuple[dict[str, str], tuple[str, ...]]:
    if len(payload) > _ARCHIVE_MAX:
        raise ValueError("theme archive exceeds the 8 MB limit")
    files: dict[str, str] = {}
    ignored: list[str] = []
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000:
            raise ValueError("theme archive contains too many entries")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            safe_name = "".join(c if c.isprintable() else "?" for c in entry.filename[:200])
            if entry.is_dir():
                continue
            if path.is_absolute() or ".." in path.parts or "\\" in entry.orig_filename:
                raise ValueError("unsafe path in theme archive")
            if stat.S_ISLNK(entry.external_attr >> 16) or path.suffix != ".toml":
                ignored.append(safe_name)
                continue
            slug, text = _read_archive_theme(archive, entry)
            if slug in files:
                raise ValueError("duplicate theme slug in archive")
            files[slug] = text
            if len(files) > _MAX_THEMES:
                raise ValueError("theme archive contains more than 20 themes")
    if not files:
        raise ValueError("repository contains no valid TOML themes")
    return files, tuple(ignored[:40])


def install_theme_data(
    content: str, *, source: str = "", update: bool = False
) -> ThemeInstallReport:
    theme = parse_theme(content)
    return _publish({theme.slug: content}, source=source, update=update)


def _publish(files: dict[str, str], *, source: str, update: bool) -> ThemeInstallReport:
    root = user_themes_dir()
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_path_lock(
        root / ".themes.lock", timeout_seconds=30, timeout_message="Theme settings are busy"
    ):
        return _publish_locked(root, files, source=source, update=update)


def _publish_locked(
    root: Path, files: dict[str, str], *, source: str, update: bool
) -> ThemeInstallReport:
    if source:
        _github_repo(source)
    builtin_slugs = {path.stem for path in BUILTIN_THEMES.glob("*.toml")}
    sources = _sources(root)
    for slug in files:
        if slug in builtin_slugs:
            raise ValueError("built-in themes cannot be overwritten")
        path = root / f"{slug}.toml"
        if path.exists() and (not update or sources.get(slug) != source):
            raise ValueError(f"theme {slug} already exists; use update for its original source")
    root.mkdir(parents=True, exist_ok=True)
    new_sources = {**sources, **dict.fromkeys(files, source)}
    encoded_sources = json.dumps(new_sources, sort_keys=True)
    if len(encoded_sources.encode("utf-8")) > 64 * 1024:
        raise ValueError("theme source registry exceeds its storage limit")
    _write_theme_batch(root, files, encoded_sources)
    return ThemeInstallReport(tuple(files))


def _write_theme_batch(root: Path, files: dict[str, str], encoded_sources: str) -> None:
    previous: dict[Path, str | None] = {}
    try:
        for slug, text in files.items():
            path = root / f"{slug}.toml"
            previous[path] = read_confined_state_text(path, root, max_bytes=THEME_MAX_BYTES)
            atomic_write_confined_text(path, text, root)
        atomic_write_confined_text(root / ".sources.json", encoded_sources, root)
    except (OSError, ValueError):
        for path, content in previous.items():
            if content is not None:
                atomic_write_confined_text(path, content, root)
            elif (identity := confined_file_identity(path, root)) is not None:
                unlink_confined_file(path, root, expected=identity)
        raise


def install_theme(target: str, *, update: bool = False) -> ThemeInstallReport:
    if target.startswith("https://"):
        owner, repo = _github_repo(target)
        with safe_urlopen(
            f"https://github.com/{owner}/{repo}/archive/HEAD.zip", timeout=30
        ) as response:
            payload = response.read(_ARCHIVE_MAX + 1)
        files, ignored = _archive_themes(payload)
        report = _publish(files, source=target, update=update)
        return ThemeInstallReport(report.installed, ignored)
    path = Path(target).expanduser().absolute()
    if path.suffix != ".toml":
        raise ValueError("local themes must be TOML files")
    text = read_confined_text(path, path.parent, max_bytes=THEME_MAX_BYTES)
    if text is None:
        raise ValueError("theme is unsafe, unreadable, or exceeds 16 KB")
    return install_theme_data(text, update=update)


def update_themes() -> tuple[ThemeInstallReport, ...]:
    return tuple(
        install_theme(source, update=True)
        for source in sorted(set(_sources(user_themes_dir()).values()))
        if source
    )


def remove_theme(slug: str) -> None:
    validate_slug(slug)
    if (BUILTIN_THEMES / f"{slug}.toml").exists():
        raise ValueError("built-in themes cannot be removed")
    root = user_themes_dir()
    if not root.exists():
        raise ValueError("user theme does not exist")
    with exclusive_path_lock(
        root / ".themes.lock", timeout_seconds=30, timeout_message="Theme settings are busy"
    ):
        _remove_theme_locked(root, slug)


def _remove_theme_locked(root: Path, slug: str) -> None:
    path = root / f"{slug}.toml"
    identity = confined_file_identity(path, root)
    if identity is None:
        raise ValueError("user theme does not exist")
    sources = _sources(root)
    content = read_confined_state_text(path, root, max_bytes=THEME_MAX_BYTES)
    if content is None:
        raise ValueError("user theme cannot be safely read")
    unlink_confined_file(path, root, expected=identity)
    sources.pop(slug, None)
    try:
        atomic_write_confined_text(
            root / ".sources.json", json.dumps(sources, sort_keys=True), root
        )
    except (OSError, ValueError):
        atomic_write_confined_text(path, content, root)
        raise


def theme_listing() -> dict[str, object]:
    return load_themes().to_row()
