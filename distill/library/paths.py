"""Artifact filename and frontmatter helpers.

Distill keeps source artifacts in nested directories for pipeline ergonomics,
but Markdown filenames need globally descriptive names so Obsidian-style vaults
do not collapse into hundreds of indistinguishable ``insights.md`` notes.
"""

# pyright: strict

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import deal

from distill.library.locking import exclusive_path_lock

__all__ = [
    "ARTIFACT_SUFFIXES",
    "LEGACY_ARTIFACT_NAMES",
    "ProvenanceFields",
    "apply_frontmatter",
    "artifact_candidate_paths",
    "artifact_exists",
    "artifact_filename",
    "artifact_identity",
    "artifact_path",
    "atomic_replace_json",
    "atomic_replace_text",
    "atomic_update_text",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "base_frontmatter",
    "dump_frontmatter",
    "extract_frontmatter",
    "find_artifact",
    "is_safe_path_slug",
    "legacy_artifact_path",
    "provenance_frontmatter",
    "read_artifact",
    "render_markdown_artifact",
    "resolve_slug_collision",
    "sanitize_path_component",
    "sanitize_topic",
    "site_name_from_url",
    "slugify_title",
    "split_frontmatter",
    "strip_frontmatter",
    "tags_for",
    "text_write_lock",
    "workspace_output_path",
    "write_markdown_artifact",
    "write_text_artifact",
]

_TEXT_WRITE_LOCK_TIMEOUT_SECONDS = 30.0
_ATOMIC_REPLACE_TIMEOUT_SECONDS = 2.0
_ATOMIC_REPLACE_RETRY_SECONDS = 0.05


class _WriteLockState(threading.local):
    """Track path locks already held by the current thread."""

    held: set[str]

    def __init__(self) -> None:
        self.held = set()


_TEXT_WRITE_LOCKS = _WriteLockState()


def _text_write_lock_path(path: Path) -> Path:
    normalized_name = os.path.normcase(path.name)
    digest = hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()
    return path.parent / f".distill-write-{digest}.lock"


def _text_write_lock_key(path: Path) -> str:
    """Return a thread-local identity for one advisory write lock."""

    return os.path.normcase(str(_text_write_lock_path(path).absolute()))


def _atomic_write_text_unlocked(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(Path(tmp), path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp).unlink()
        raise


def _atomic_write_bytes_unlocked(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(Path(tmp), path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp).unlink()
        raise


def _replace_with_retry(source: Path, target: Path) -> None:
    """Replace a file, tolerating brief Windows reader sharing conflicts."""

    deadline = time.monotonic() + _ATOMIC_REPLACE_TIMEOUT_SECONDS
    while True:
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            if not _is_retryable_replace_error(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(_ATOMIC_REPLACE_RETRY_SECONDS)


def _is_retryable_replace_error(_error: PermissionError) -> bool:
    return os.name == "nt"


@contextlib.contextmanager
def text_write_lock(path: Path) -> Generator[None]:
    """Hold the lock shared by atomic writes and read-modify-write transactions."""

    key = _text_write_lock_key(path)
    held = _TEXT_WRITE_LOCKS.held
    if key in held:
        yield
        return
    with exclusive_path_lock(
        _text_write_lock_path(path),
        timeout_seconds=_TEXT_WRITE_LOCK_TIMEOUT_SECONDS,
        timeout_message=f"Timed out writing {path}",
    ):
        held.add(key)
        try:
            yield
        finally:
            held.remove(key)


def atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically, durably, and serially.

    Creates a uniquely-named temp file in the destination directory via
    ``mkstemp`` (O_EXCL, so a pre-placed symlink at a predictable ``.tmp`` name
    cannot redirect the write), fsyncs it, then ``os.replace``s it onto the final
    name. Replacement is atomic on the same filesystem, so readers see either
    complete version, never a torn file. A per-path advisory lock serializes
    cooperating writers and read-modify-write transactions. The temp file is
    removed if anything fails before the rename.
    """
    with text_write_lock(path):
        _atomic_write_text_unlocked(path, content)


def atomic_replace_text(path: Path, content: str) -> None:
    """Atomically replace text in a private single-writer staging directory.

    Unlike :func:`atomic_write_text`, this helper does not create a persistent
    advisory lock file. Callers must use it only where one process exclusively
    owns the containing directory.
    """

    _atomic_write_text_unlocked(path, content)


def atomic_replace_json(path: Path, value: object, *, indent: int = 2) -> None:
    """Serialize strict JSON through :func:`atomic_replace_text`."""

    atomic_replace_text(
        path,
        json.dumps(value, indent=indent, ensure_ascii=False, allow_nan=False) + "\n",
    )


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write binary ``content`` atomically, durably, and serially."""

    with text_write_lock(path):
        _atomic_write_bytes_unlocked(path, content)


def atomic_write_json(path: Path, value: object, *, indent: int = 2) -> None:
    """Serialize ``value`` as UTF-8 JSON and write it atomically.

    ``allow_nan=False`` refuses NaN/Inf so the file stays JSON-compliant.
    """

    atomic_write_text(
        path,
        json.dumps(value, indent=indent, ensure_ascii=False, allow_nan=False) + "\n",
    )


def workspace_output_path(library_dir: Path, filename: str) -> Path:
    """Return a confined path in the output directory beside ``library_dir``."""

    output_dir = library_dir.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_filename = sanitize_path_component(str(filename)).lstrip(". ") or "untitled"
    return output_dir / safe_filename


def atomic_update_text[UpdateResult](
    path: Path,
    update: Callable[[str], tuple[str, UpdateResult]],
    *,
    missing: str | None = None,
    max_bytes: int | None = None,
    recover_invalid: Callable[[BaseException], str] | None = None,
) -> UpdateResult:
    """Read, derive, and conditionally replace text under its write lock.

    When ``missing`` is supplied, a path that does not yet exist is treated as
    that text and created under the same lock. The default preserves the prior
    behavior of raising ``FileNotFoundError`` for a missing path.
    """

    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    with text_write_lock(path):
        path_was_missing = False
        try:
            if max_bytes is None:
                current = path.read_text(encoding="utf-8")
            else:
                with path.open("rb") as stream:
                    raw = stream.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise ValueError(f"State file exceeds the {max_bytes:,}-byte limit: {path}")
                current = raw.decode("utf-8")
        except FileNotFoundError:
            if missing is None:
                raise
            current = missing
            path_was_missing = True
        except (UnicodeDecodeError, ValueError) as exc:
            if recover_invalid is None:
                raise
            current = recover_invalid(exc)
        replacement, result = update(current)
        if path_was_missing or replacement != current:
            _atomic_write_text_unlocked(path, replacement)
        return result


_ARTIFACT_SUFFIXES = {
    "answer": "Answer",
    "audit": "Audit",
    "brief": "Brief",
    "content": "Content",
    "corpus_synthesis": "Corpus_Synthesis",
    "episode": "Episode",
    "insights": "Insights",
    "latest_changes": "Latest_Changes",
    "paper": "Paper",
    "paper_synthesis": "Paper_Synthesis",
    "repo": "Repo",
    "report": "Report",
    "research": "Research",
    "site_synthesis": "Site_Synthesis",
    "site_update": "Site_Update",
    "synthesis": "Synthesis",
    "topic_synthesis": "Topic_Synthesis",
    "topic_diff": "Topic_Diff",
    "topic_trends": "Topic_Trends",
    "transcript": "Transcript",
    "tweet": "Tweet",
    "verify": "Verify",
    "watch_alerts": "Watch_Alerts",
    "watch_update": "Watch_Update",
}

_LEGACY_NAMES = {
    "answer": "answer.md",
    "audit": "audit.md",
    "brief": "brief.md",
    "content": "content.md",
    "corpus_synthesis": "corpus_synthesis.md",
    "episode": "episode.md",
    "insights": "insights.md",
    "latest_changes": "latest_changes.md",
    "paper": "paper.md",
    "paper_synthesis": "paper_synthesis.md",
    "repo": "repo.md",
    "report": "report.md",
    "research": "research.md",
    "site_synthesis": "synthesis.md",
    "site_update": "site_update.md",
    "synthesis": "synthesis.md",
    "topic_synthesis": "topic_synthesis.md",
    "topic_diff": "topic_diff.md",
    "topic_trends": "topic_trends.md",
    "transcript": "transcript.txt",
    "tweet": "tweet.md",
    "verify": "verify.json",
    "watch_alerts": "watch_alerts.md",
    "watch_update": "watch_update.md",
}

# Public aliases for the artifact name maps (used by WikiLink and migration tooling)
ARTIFACT_SUFFIXES: dict[str, str] = _ARTIFACT_SUFFIXES
LEGACY_ARTIFACT_NAMES: dict[str, str] = _LEGACY_NAMES

_WINDOWS_RESERVED_CHARS = r'[<>:"/\\|?*]'
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


# ---------------------------------------------------------------------------
# Provenance dataclass and helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProvenanceFields:
    """Exact generation context for an artifact."""

    model: str
    model_version: str
    temperature: float
    prompt_id: str


def provenance_frontmatter(provenance: ProvenanceFields) -> dict[str, Any]:
    """Return provenance fields as a frontmatter-ready dict."""
    return {
        "model": provenance.model,
        "model_version": provenance.model_version,
        "temperature": provenance.temperature,
        "prompt_id": provenance.prompt_id,
    }


# ---------------------------------------------------------------------------
# Path / slug utilities (relocated from config.py)
# ---------------------------------------------------------------------------


def is_safe_path_slug(slug: str) -> bool:
    """Return whether ``slug`` is one safe directory or note component.

    Rejects traversal, drive letters, null bytes, and Windows reserved
    device names (including ``con.md``). Callers still confine the parent.
    """
    if not slug or "\x00" in slug:
        return False
    if "/" in slug or "\\" in slug or ":" in slug or slug in {".", ".."}:
        return False
    if slug.casefold().partition(".")[0] in _WINDOWS_RESERVED_NAMES:
        return False
    return slug == Path(slug).name


def _is_single_path_component(value: str) -> bool:
    """A sanitized name must stay within one directory level.

    Every caller joins the result straight into a corpus path, so the
    confinement guarantee is: no path separator, no NUL, and never empty.
    This is the load-bearing path-traversal defense, made executable.
    """
    return bool(value) and "/" not in value and "\\" not in value and "\x00" not in value


@deal.post(_is_single_path_component)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
def slugify_title(title: str, source_id: str = "", max_len: int = 60) -> str:
    """Convert a title or label to a clean directory name.

    Determinism guarantee: same (title, source_id) → same slug, always.
    Cross-platform: no Windows reserved chars, no trailing dots/spaces, ≤255 bytes.
    """
    slug = title.lower()
    slug = re.sub(r"[''`]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    # Avoid Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    if slug in _WINDOWS_RESERVED_NAMES:
        slug = f"_{slug}"
    if source_id:
        # Sanitize source_id: lowercase, keep only [a-z0-9], truncate to 8
        clean_id = re.sub(r"[^a-z0-9]", "", source_id[:8].lower())
        if clean_id:
            slug = f"{slug}_{clean_id}"
    return slug or "untitled"


@deal.post(_is_single_path_component)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
def sanitize_path_component(value: str) -> str:
    """Make a human-readable filesystem-safe path segment.

    This is primarily needed for Windows-invalid names like
    'AI News & Strategy Daily | Nate B Jones'.
    """
    # Strip control characters (NUL + other C0 + DEL) first: they are not Windows
    # reserved punctuation but are filesystem-dangerous (a NUL can truncate a path
    # at the C level). \t\n\r are left for the \s+ collapse below to turn into
    # spaces, preserving word separation.
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    cleaned = re.sub(_WINDOWS_RESERVED_CHARS, "-", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if cleaned.casefold().partition(".")[0] in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned or "untitled"


@deal.post(_is_single_path_component)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
def sanitize_topic(value: object) -> str:
    """Sanitize a topic so it is always a single safe directory component.

    Untrusted callers (MCP tools, CLI flags) can pass values like ``../../etc``
    or ``/tmp/x`` -- and, since the value crosses an untrusted boundary, a
    non-string (e.g. an MCP client sending a number). ``value`` is typed
    ``object`` so the runtime guard below is a real defense, not dead code:
    this collapses path separators, rejects traversal-only segments, and falls
    back to ``"untitled"`` rather than letting the path join escape the topics
    root.
    """
    if not isinstance(value, str):
        return "untitled"
    # Strip leading dots so values like ``.env`` or ``..foo`` cannot point at
    # hidden parent-directory neighbours when used as a directory component.
    pre = value.lstrip(".") if value else ""
    cleaned = sanitize_path_component(pre)
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    cleaned = cleaned.strip("-. ")
    if not cleaned or cleaned == "untitled":
        return "untitled"
    return cleaned


def site_name_from_url(url: str) -> str:
    """Derive a readable site identifier from a URL host.

    ``netloc`` retains any ``user:pass@`` prefix, so a seed URL carrying inline
    credentials used to bake them into the derived site name -- which becomes a
    corpus *directory name* on disk and is also sent to the rerank model. Drop
    everything before the last ``@`` so only host (and any explicit port, which
    callers rely on for identity) survives.
    """
    host = urlparse(url).netloc.lower()
    host = host.rpartition("@")[2]
    host = host.removeprefix("www.")
    return sanitize_path_component(host or "site")


def resolve_slug_collision(
    target_dir: Path,
    slug: str,
    source_type: str,
    source_id: str,
) -> str:
    """Append disambiguating suffix if slug already maps to a different source.

    Checks whether *slug* already exists in *target_dir* for a different
    (source_type, source_id) pair. If so, appends ``_2``, ``_3``, etc. until
    a unique slug is found.
    """
    candidate = slug
    counter = 1
    while True:
        candidate_path = target_dir / candidate
        if not candidate_path.exists():
            # No collision, slug is available.
            return candidate
        # Check if the existing directory belongs to the same source
        meta_file = candidate_path / ".source_meta.json"
        if meta_file.exists():
            try:
                raw_meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta = (
                    cast("Mapping[str, object]", raw_meta)
                    if isinstance(raw_meta, Mapping)
                    else None
                )
            except (OSError, RecursionError, UnicodeError, ValueError):
                meta = None
            if (
                meta is not None
                and meta.get("source_type") == source_type
                and meta.get("source_id") == source_id
            ):
                # Same source, reuse the slug.
                return candidate
        # Different source or unreadable meta, try next suffix.
        counter += 1
        candidate = f"{slug}_{counter}"


def artifact_identity(*parts: str | None) -> str:
    """Build a filesystem-safe identity stem from meaningful context parts."""
    cleaned_parts = [_filename_stem(part or "") for part in parts if part]
    return "_".join(part for part in cleaned_parts if part) or "untitled"


def artifact_filename(identity: str, artifact_type: str, *, extension: str = "md") -> str:
    suffix = _ARTIFACT_SUFFIXES.get(artifact_type, artifact_type.title().replace("-", "_"))
    stem = artifact_identity(identity)
    return f"{stem}_{suffix}.{extension.lstrip('.')}"


def artifact_path(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
) -> Path:
    """Return the modern, Obsidian-friendly artifact path for a directory."""
    return directory / artifact_filename(
        identity or directory.name, artifact_type, extension=extension
    )


def legacy_artifact_path(directory: Path, artifact_type: str) -> Path:
    return directory / _LEGACY_NAMES[artifact_type]


def _lowercase_suffix_artifact_path(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
) -> Path:
    suffix = _ARTIFACT_SUFFIXES.get(artifact_type, artifact_type.title().replace("-", "_"))
    stem = artifact_identity(identity or directory.name)
    return directory / f"{stem}_{suffix.casefold()}.{extension.lstrip('.')}"


def artifact_candidate_paths(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
) -> tuple[Path, ...]:
    """Return reader candidates in compatibility precedence order.

    The first path is the canonical writer path. The remaining paths preserve
    compatibility with the early lowercase-suffix convention and legacy
    fixed filenames.
    """
    modern = artifact_path(directory, artifact_type, identity=identity, extension=extension)
    lowercase_suffix = _lowercase_suffix_artifact_path(
        directory, artifact_type, identity=identity, extension=extension
    )
    legacy = legacy_artifact_path(directory, artifact_type)
    candidates = (modern, lowercase_suffix, legacy)
    return tuple(
        candidate
        for index, candidate in enumerate(candidates)
        if str(candidate) not in {str(previous) for previous in candidates[:index]}
    )


def find_artifact(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
) -> Path:
    """Return the modern artifact if present, otherwise the legacy path.

    The returned path may not exist. New callers should write to
    :func:`artifact_path`; readers should use this helper so older libraries
    continue to work.
    """
    candidates = artifact_candidate_paths(
        directory, artifact_type, identity=identity, extension=extension
    )
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def artifact_exists(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
) -> bool:
    return find_artifact(directory, artifact_type, identity=identity, extension=extension).exists()


def read_artifact(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
    encoding: str = "utf-8",
) -> str:
    return find_artifact(
        directory, artifact_type, identity=identity, extension=extension
    ).read_text(encoding=encoding)


def write_text_artifact(
    directory: Path,
    artifact_type: str,
    content: str,
    *,
    identity: str | None = None,
    extension: str = "md",
    encoding: str = "utf-8",
) -> Path:
    path = artifact_path(directory, artifact_type, identity=identity, extension=extension)
    atomic_write_text(path, content)
    return path


# A line that is exactly a bold-wrapped ATX heading (``**## Title**``). Models
# sometimes emphasize the heading lines a prompt asked for; the result renders
# as literal ``**##`` text instead of a heading in Obsidian and on GitHub.
_BOLD_WRAPPED_HEADING_RE = re.compile(r"^(\s*)\*\*(#{1,6} .+?)\*\*\s*$")


def normalize_markdown_headings(content: str) -> str:
    """Unwrap bold-wrapped ATX headings (``**## Title**`` -> ``## Title``).

    Only whole lines that are a bold-wrapped heading are rewritten -- legitimate
    bold prose never starts with ``#``, and bold *inside* a heading
    (``## **Title**``) is valid markdown and untouched. Lines inside fenced
    code blocks are left alone.
    """
    lines = content.split("\n")
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _BOLD_WRAPPED_HEADING_RE.match(line)
        if match:
            lines[i] = f"{match.group(1)}{match.group(2)}"
    return "\n".join(lines)


# Artifact types that capture a source verbatim (receipts). Their punctuation is
# part of the source, so dash normalization is skipped to preserve provenance
# fidelity; it applies only to distillr's own authored prose.
_SOURCE_CAPTURE_TYPES = frozenset(
    {"content", "paper", "transcript", "episode", "tweet", "repo", "verify"}
)

_EM_DASH_RE = re.compile(r"\s*—\s*")


def normalize_dashes(content: str) -> str:
    """Replace em-dashes with ``' - '`` outside fenced code blocks.

    distillr's house style forbids em-dashes in authored prose; models emit them
    anyway. Enforcing the rule deterministically at the write boundary keeps
    every authored artifact clean regardless of model behavior. Lines inside
    fenced code blocks are left intact so example snippets are not rewritten.
    """
    lines = content.split("\n")
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        lines[i] = _EM_DASH_RE.sub(" - ", line)
    return "\n".join(lines)


def write_markdown_artifact(
    directory: Path,
    artifact_type: str,
    content: str,
    *,
    identity: str | None = None,
    frontmatter: Mapping[str, Any] | None = None,
) -> Path:
    content = render_markdown_artifact(
        artifact_type,
        content,
        frontmatter=frontmatter,
    )
    return write_text_artifact(directory, artifact_type, content, identity=identity)


def render_markdown_artifact(
    artifact_type: str,
    content: str,
    *,
    frontmatter: Mapping[str, Any] | None = None,
) -> str:
    """Return the exact normalized text that the artifact writer persists."""

    content = normalize_markdown_headings(content)
    if artifact_type not in _SOURCE_CAPTURE_TYPES:
        content = normalize_dashes(content)
    if frontmatter:
        content = apply_frontmatter(content, frontmatter)
    return content


def _parse_scalar_or_list(value: str) -> str | list[str]:
    """Parse an inline-list frontmatter string (``["a", "b"]``) back into a list.

    ``extract_frontmatter`` returns every value as a string. When
    ``apply_frontmatter`` carries a pre-existing list field forward (because the
    incoming frontmatter doesn't re-supply it), re-dumping the raw string would
    emit ``tags: "[a, b]"`` -- a list silently turned into a quoted scalar.
    Parsing it back keeps the round-trip honest. ``dump_frontmatter`` always
    emits lists as valid JSON arrays, so a quote-aware ``json.loads`` round-trips
    them exactly; anything that isn't a JSON array passes through unchanged.
    """
    s = value.strip()
    if not (len(s) >= 2 and s[0] == "[" and s[-1] == "]"):
        return value
    try:
        parsed = json.loads(s)
    except (ValueError, TypeError):
        return value
    except RecursionError:
        # A deeply nested array (e.g. attacker-influenced LLM frontmatter like
        # "[[[[...]]]]") overflows json.loads's recursion. This is carried-forward
        # *existing* frontmatter, not a re-supplied field, so treating an
        # unparseable value as an opaque scalar keeps the artifact write alive
        # instead of aborting the ingestion/report on a hostile note.
        return value
    return (
        [str(item) for item in cast("list[object]", parsed)] if isinstance(parsed, list) else value
    )


def _frontmatter_value_is_emitted(value: Any) -> bool:
    return not (value is None or value == "" or value == [] or value == {})


def _emitted_frontmatter_keys(frontmatter: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for key, value in frontmatter.items():
        dumped_key = _yaml_key(str(key))
        if dumped_key and _frontmatter_value_is_emitted(value):
            keys.add(dumped_key)
    return keys


def _dump_frontmatter_round_trips_keys(frontmatter: Mapping[str, Any], *, result: str) -> bool:
    block, body = split_frontmatter(result)
    if block is None or body != "":
        return False
    return set(extract_frontmatter(result)) == _emitted_frontmatter_keys(frontmatter)


def _apply_frontmatter_shape(content: str, frontmatter: Mapping[str, Any], *, result: str) -> bool:
    block, _body = split_frontmatter(result)
    if block is None or not result.endswith("\n"):
        return False
    if not _emitted_frontmatter_keys(frontmatter).issubset(set(extract_frontmatter(result))):
        return False
    return strip_frontmatter(result) == strip_frontmatter(content).lstrip().rstrip()


@deal.ensure(_apply_frontmatter_shape)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
def apply_frontmatter(content: str, frontmatter: Mapping[str, Any]) -> str:
    """Replace any existing frontmatter with a normalized YAML block."""
    existing: dict[str, Any] = {
        key: _parse_scalar_or_list(value)
        for key, value in extract_frontmatter(content).items()
        if key not in {"paper_title", "video_title", "page_title"}
    }
    merged = {**existing, **dict(frontmatter)}
    body = strip_frontmatter(content).lstrip()
    return dump_frontmatter(merged) + "\n\n" + body.rstrip() + "\n"


def _split_physical_lines(content: str) -> list[str]:
    if content == "":
        return []
    parts = re.split(r"(\r\n|\n|\r)", content)
    lines: list[str] = []
    for index in range(0, len(parts), 2):
        text = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        if text or separator:
            lines.append(text + separator)
    return lines


def split_frontmatter(content: str) -> tuple[str | None, str]:
    """Split content into ``(frontmatter_block, body)``.

    A frontmatter block exists only when the first line is exactly ``---`` and a
    later line is exactly ``---`` (the closing fence). This fence-based detection
    -- rather than ``content.split("---", 2)`` -- means a body that opens with a
    ``---`` horizontal rule, or a frontmatter *value* that contains ``---`` (an
    em-dash-style title, a URL), is no longer misparsed. The old split silently
    dropped the body or truncated the block mid-value, losing every field after
    the embedded ``---``. Returns ``(None, content)`` when there is no fence.
    """
    if not content.startswith("---"):
        return None, content
    lines = _split_physical_lines(content)
    if not lines or lines[0].strip() != "---":
        return None, content
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1 :])
    return None, content


def extract_frontmatter(content: str) -> dict[str, str]:
    """Extract simple scalar YAML frontmatter without adding a YAML dependency."""
    block, _ = split_frontmatter(content)
    if block is None:
        return {}
    data: dict[str, str] = {}
    for line in _split_physical_lines(block):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = _unquote_frontmatter_value(value.strip())
        if key:
            data[key] = value
    return data


def _unquote_frontmatter_value(value: str) -> str:
    """Invert ``_yaml_value``'s JSON quoting for a scalar frontmatter value.

    ``dump_frontmatter`` writes scalars with ``json.dumps``, so a value containing
    a quote or backslash is escaped. Unquoting with a bare ``strip('"')`` left the
    escapes in place, and because ``apply_frontmatter`` carries un-resupplied keys
    forward through this reader, every rewrite re-escaped already-escaped text and
    doubled the backslashes. That silently corrupted persisted title, URL, and
    author provenance (and anything derived from it, such as exported OKF
    bundles). Decoding properly keeps ``dump(extract(x)) == x`` a fixed point.
    """
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
        except ValueError:
            return value.strip('"')
        if isinstance(decoded, str):
            return decoded
    return value.strip('"')


def strip_frontmatter(content: str) -> str:
    block, body = split_frontmatter(content)
    if block is None:
        return content
    return body.strip()


@deal.ensure(_dump_frontmatter_round_trips_keys)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
def dump_frontmatter(frontmatter: Mapping[str, Any]) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        yaml_key = _yaml_key(str(key))
        if not yaml_key:
            continue
        lines.append(f"{yaml_key}: {_yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def base_frontmatter(
    *,
    artifact_type: str,
    title: str,
    topic: str = "",
    source: str = "",
    source_id: str = "",
    url: str = "",
    date: str = "",
    authors: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    synthesis_scope: str = "",
    extra: Mapping[str, Any] | None = None,
    provenance: ProvenanceFields | None = None,
) -> dict[str, Any]:
    # NOTE: the field was named ``confidence`` pre-0.8.1. Values like
    # ``single-paper`` / ``corpus-consensus`` / ``interpretation`` describe
    # the *scope* of the artifact (which sources fed it), not a calibrated
    # confidence number. Renamed to ``synthesis_scope`` so downstream
    # consumers don't treat the routing label as a numeric grade.
    # ``distill doctor --migrate-frontmatter`` rewrites pre-0.8.1 artifacts.
    data: dict[str, Any] = {
        "title": title,
        "type": artifact_type,
        "topic": topic,
        "source": source,
        "source_id": source_id,
        "url": url,
        "date": date,
        "authors": list(authors or []),
        "tags": list(tags or []),
        "synthesis_scope": synthesis_scope,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        for key, value in extra.items():
            if key not in data or data[key] in ("", [], {}):
                data[key] = value
    if provenance:
        prov_dict = provenance_frontmatter(provenance)
        for key, value in prov_dict.items():
            if key not in data or data[key] in ("", [], {}):
                data[key] = value
    return data


def tags_for(topic: str = "", *parts: str) -> list[str]:
    tags: list[str] = []
    if topic:
        tags.append(f"distill/{artifact_identity(topic)}")
    for part in parts:
        if part:
            tags.append(f"source/{artifact_identity(part)}")
    return tags


def _filename_stem(value: str) -> str:
    cleaned = value.replace("&", " and ")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "untitled"


def _yaml_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", key)


def _yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return "[" + ", ".join(_yaml_value(item) for item in cast("Sequence[object]", value)) + "]"
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return json.dumps(str(value), ensure_ascii=False)
