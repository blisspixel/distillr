"""Property-based tests for distill.library.paths slug utilities.

Feature: living-wiki-0-7
"""

from __future__ import annotations

import json
import re
import tempfile
import tempfile as _tempfile
from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from distill.library.migration import (
    _REVERSE_LEGACY,
    scan_legacy_artifacts,
)
from distill.library.paths import (
    _ARTIFACT_SUFFIXES,
    _LEGACY_NAMES,
    resolve_slug_collision,
    slugify_title,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid titles: non-empty strings with printable characters (unicode letters,
# numbers, punctuation, symbols, separators)
titles = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=200,
)

# Source IDs: alphanumeric strings (video IDs, paper IDs, URL hashes)
source_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=0,
    max_size=20,
)

# Aggressive unicode titles for filesystem safety testing
unicode_titles = st.text(min_size=1, max_size=300)

# Long byte-heavy titles (characters that expand to multiple bytes in UTF-8)
long_titles = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z", "M")),
    min_size=100,
    max_size=500,
)


# ---------------------------------------------------------------------------
# Property 2: Slug determinism (idempotence)
# Feature: living-wiki-0-7, Property 2: Slug determinism
# ---------------------------------------------------------------------------


class TestSlugDeterminism:
    """Property 2: Slug determinism (idempotence).

    For any (title, source_id) pair, calling slugify_title(title, source_id)
    multiple times SHALL always produce the same output string.

    **Validates: Requirements 2.1, 7.7**
    """

    @given(title=titles, source_id=source_ids)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_same_inputs_produce_same_output(self, title: str, source_id: str) -> None:
        """slugify_title is deterministic: same inputs → same output."""
        result1 = slugify_title(title, source_id)
        result2 = slugify_title(title, source_id)
        result3 = slugify_title(title, source_id)
        assert result1 == result2 == result3

    @given(title=titles, source_id=source_ids)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_determinism_with_explicit_max_len(self, title: str, source_id: str) -> None:
        """slugify_title is deterministic regardless of when it's called."""
        for max_len in (30, 60, 100):
            result1 = slugify_title(title, source_id, max_len=max_len)
            result2 = slugify_title(title, source_id, max_len=max_len)
            assert result1 == result2


# ---------------------------------------------------------------------------
# Property 3: Slug filesystem safety
# Feature: living-wiki-0-7, Property 3: Slug filesystem safety
# ---------------------------------------------------------------------------

# Regex for allowed slug characters
_VALID_SLUG_CHARS = re.compile(r"^[a-z0-9\-_]+$")

# Windows reserved characters
_WINDOWS_RESERVED_CHARS = set('<>:"/\\|?*')


class TestSlugFilesystemSafety:
    """Property 3: Slug filesystem safety.

    For any input string (including unicode, special characters, and strings
    exceeding 255 bytes), slugify_title SHALL produce output containing only
    characters in [a-z0-9-_], with no trailing dots or spaces, no Windows-
    reserved characters, and total byte length ≤ 255.

    **Validates: Requirements 2.2**
    """

    @given(title=unicode_titles, source_id=source_ids)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_output_contains_only_valid_chars(self, title: str, source_id: str) -> None:
        """Slug contains only lowercase alphanumeric, hyphens, and underscores."""
        slug = slugify_title(title, source_id)
        assert _VALID_SLUG_CHARS.match(slug), f"Slug {slug!r} contains invalid characters"

    @given(title=unicode_titles, source_id=source_ids)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_no_trailing_dots_or_spaces(self, title: str, source_id: str) -> None:
        """Slug has no trailing dots or spaces."""
        slug = slugify_title(title, source_id)
        assert not slug.endswith("."), f"Slug {slug!r} ends with a dot"
        assert not slug.endswith(" "), f"Slug {slug!r} ends with a space"

    @given(title=unicode_titles, source_id=source_ids)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_no_windows_reserved_chars(self, title: str, source_id: str) -> None:
        """Slug contains no Windows-reserved characters."""
        slug = slugify_title(title, source_id)
        for char in slug:
            assert char not in _WINDOWS_RESERVED_CHARS, (
                f"Slug {slug!r} contains Windows-reserved char {char!r}"
            )

    @given(title=unicode_titles, source_id=source_ids)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_byte_length_within_limit(self, title: str, source_id: str) -> None:
        """Slug byte length is ≤ 255 (filesystem limit)."""
        slug = slugify_title(title, source_id)
        byte_len = len(slug.encode("utf-8"))
        assert byte_len <= 255, f"Slug {slug!r} has byte length {byte_len} > 255"

    @given(title=long_titles, source_id=source_ids)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_long_inputs_still_safe(self, title: str, source_id: str) -> None:
        """Even very long inputs produce safe slugs within byte limits."""
        slug = slugify_title(title, source_id)
        assert _VALID_SLUG_CHARS.match(slug)
        assert len(slug.encode("utf-8")) <= 255

    @given(title=titles, source_id=source_ids)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_slug_is_non_empty(self, title: str, source_id: str) -> None:
        """Slug is never empty (falls back to 'untitled' if needed)."""
        slug = slugify_title(title, source_id)
        assert len(slug) > 0


# ---------------------------------------------------------------------------
# Property 4: Slug collision disambiguation
# Feature: living-wiki-0-7, Property 4: Slug collision disambiguation
# ---------------------------------------------------------------------------


class TestSlugCollisionDisambiguation:
    """Property 4: Slug collision disambiguation.

    For any two distinct (source_type, source_id) pairs that produce the same
    base slug within a target directory, resolve_slug_collision SHALL return
    distinct slugs for each, with the second receiving a disambiguating suffix.

    **Validates: Requirements 2.4, 2.5**
    """

    @given(
        title=titles,
        source_id_a=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=10,
        ),
        source_id_b=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_distinct_sources_get_distinct_slugs(
        self, title: str, source_id_a: str, source_id_b: str
    ) -> None:
        """Two distinct sources with the same base slug get different final slugs."""
        assume(source_id_a != source_id_b)

        base_slug = slugify_title(title, source_id_a)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # First source claims the slug by creating the directory with metadata
            first_dir = tmp_path / base_slug
            first_dir.mkdir(parents=True)
            meta = {"source_type": "video", "source_id": source_id_a}
            (first_dir / ".source_meta.json").write_text(json.dumps(meta), encoding="utf-8")

            # First source should get the original slug back
            slug_a = resolve_slug_collision(tmp_path, base_slug, "video", source_id_a)

            # Second source (different source_id) should get a disambiguated slug
            slug_b = resolve_slug_collision(tmp_path, base_slug, "video", source_id_b)

            assert slug_a != slug_b, f"Expected distinct slugs but both got {slug_a!r}"

    @given(
        title=titles,
        source_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_same_source_reuses_slug(self, title: str, source_id: str) -> None:
        """Same source always gets the same slug (no unnecessary disambiguation)."""
        base_slug = slugify_title(title, source_id)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create directory with metadata for this source
            first_dir = tmp_path / base_slug
            first_dir.mkdir(parents=True)
            meta = {"source_type": "video", "source_id": source_id}
            (first_dir / ".source_meta.json").write_text(json.dumps(meta), encoding="utf-8")

            # Same source should get the original slug
            resolved = resolve_slug_collision(tmp_path, base_slug, "video", source_id)
            assert resolved == base_slug

    @given(
        source_type_a=st.sampled_from(["video", "paper", "page", "site"]),
        source_type_b=st.sampled_from(["video", "paper", "page", "site"]),
        source_id_a=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=10,
        ),
        source_id_b=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_different_source_types_also_disambiguated(
        self,
        source_type_a: str,
        source_type_b: str,
        source_id_a: str,
        source_id_b: str,
    ) -> None:
        """Different (source_type, source_id) pairs get distinct slugs."""
        assume((source_type_a, source_id_a) != (source_type_b, source_id_b))

        base_slug = "test-slug"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # First source claims the slug
            first_dir = tmp_path / base_slug
            first_dir.mkdir(parents=True)
            meta = {"source_type": source_type_a, "source_id": source_id_a}
            (first_dir / ".source_meta.json").write_text(json.dumps(meta), encoding="utf-8")

            # Resolve for first source
            slug_a = resolve_slug_collision(tmp_path, base_slug, source_type_a, source_id_a)

            # Resolve for second source (different pair)
            slug_b = resolve_slug_collision(tmp_path, base_slug, source_type_b, source_id_b)

            assert slug_a != slug_b, (
                f"Expected distinct slugs for different sources but both got {slug_a!r}"
            )


# ---------------------------------------------------------------------------
# Property 12: Legacy artifact detection and rename correctness
# Feature: living-wiki-0-7, Property 12: Legacy artifact detection and rename
# ---------------------------------------------------------------------------

# Strategy for valid directory slugs (simulating parent dirs created by slugify_title)
dir_slugs = st.from_regex(r"[a-z][a-z0-9\-_]{2,30}", fullmatch=True)

# Strategy for selecting a legacy artifact type
legacy_types = st.sampled_from(list(_LEGACY_NAMES.keys()))


class TestLegacyArtifactDetectionAndRename:
    """Property 12: Legacy artifact detection and rename correctness.

    For any artifact file matching a legacy naming pattern (e.g., insights.md,
    synthesis.md), scan_legacy_artifacts SHALL detect it AND the proposed rename
    SHALL produce a filename matching the modern convention <slug>_<Suffix>.md
    where slug is derived from the parent directory name.

    **Validates: Requirements 10.1, 10.2**
    """

    @given(slug=dir_slugs, artifact_type=legacy_types)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_legacy_file_detected_and_rename_correct(self, slug: str, artifact_type: str) -> None:
        """Any file matching a legacy pattern is detected with correct rename."""
        legacy_filename = _LEGACY_NAMES[artifact_type]
        # The reverse lookup determines which type the migration tool will use
        # when multiple types share the same legacy filename.
        resolved_type = _REVERSE_LEGACY[legacy_filename]
        expected_suffix = _ARTIFACT_SUFFIXES[resolved_type]
        extension = Path(legacy_filename).suffix  # .md or .txt

        with _tempfile.TemporaryDirectory() as tmp:
            library_dir = Path(tmp)
            # Create a nested directory structure simulating a real corpus
            artifact_dir = library_dir / "topics" / "test-topic" / slug
            artifact_dir.mkdir(parents=True)
            legacy_file = artifact_dir / legacy_filename
            legacy_file.write_text("# Test content\n", encoding="utf-8")

            # Scan should detect the legacy file
            actions = scan_legacy_artifacts(library_dir)

            # Filter to our specific file
            matching = [a for a in actions if a.source_path == legacy_file]
            assert len(matching) == 1, f"Expected 1 action for {legacy_file}, got {len(matching)}"

            action = matching[0]
            assert action.action_type == "rename"
            assert action.source_path == legacy_file

            # Verify the target filename matches modern convention
            expected_name = f"{slug}_{expected_suffix}{extension}"
            assert action.target_path.name == expected_name, (
                f"Expected target name {expected_name!r}, got {action.target_path.name!r}"
            )
            # Target should be in the same directory
            assert action.target_path.parent == legacy_file.parent

    @given(
        slug=dir_slugs,
        types=st.lists(legacy_types, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_multiple_legacy_files_all_detected(self, slug: str, types: list[str]) -> None:
        """Multiple legacy files in the same directory are all detected."""
        with _tempfile.TemporaryDirectory() as tmp:
            library_dir = Path(tmp)
            artifact_dir = library_dir / "topics" / slug
            artifact_dir.mkdir(parents=True)

            created_files = []
            for artifact_type in types:
                legacy_filename = _LEGACY_NAMES[artifact_type]
                legacy_file = artifact_dir / legacy_filename
                # Some types share the same filename (e.g., site_synthesis and
                # synthesis both map to synthesis.md). Skip duplicates.
                if legacy_file.exists():
                    continue
                legacy_file.write_text("# Content\n", encoding="utf-8")
                created_files.append(legacy_file)

            actions = scan_legacy_artifacts(library_dir)
            detected_sources = {a.source_path for a in actions}

            for f in created_files:
                assert f in detected_sources, f"Legacy file {f.name} was not detected"

    @given(slug=dir_slugs, artifact_type=legacy_types)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_modern_named_files_not_detected(self, slug: str, artifact_type: str) -> None:
        """Files already using modern naming are NOT detected as legacy."""
        suffix = _ARTIFACT_SUFFIXES[artifact_type]
        modern_name = f"{slug}_{suffix}.md"

        with _tempfile.TemporaryDirectory() as tmp:
            library_dir = Path(tmp)
            artifact_dir = library_dir / "topics" / slug
            artifact_dir.mkdir(parents=True)
            modern_file = artifact_dir / modern_name
            modern_file.write_text("# Modern content\n", encoding="utf-8")

            actions = scan_legacy_artifacts(library_dir)
            detected_sources = {a.source_path for a in actions}

            assert modern_file not in detected_sources, (
                f"Modern file {modern_name} should not be detected as legacy"
            )
