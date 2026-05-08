"""Property-based tests for distill.library.wikilinks.

Feature: living-wiki-0-7
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from distill.library.paths import ARTIFACT_SUFFIXES, slugify_title
from distill.library.wikilinks import WikiLink

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid titles: non-empty strings with printable characters
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

# Artifact types drawn from the known suffix map
artifact_types = st.sampled_from(list(ARTIFACT_SUFFIXES.keys()))


# ---------------------------------------------------------------------------
# Property 1: Wiki-link emission format and slug consistency
# Feature: living-wiki-0-7, Property 1: Wiki-link emission format
# ---------------------------------------------------------------------------


class TestWikiLinkEmissionFormat:
    """Property 1: Wiki-link emission format and slug consistency.

    For any valid (title, source_id, artifact_type) triple, the rendered
    wiki-link SHALL have the format [[slugify_title(title, source_id)_Suffix|title]]
    where Suffix is the artifact suffix for the given type, the slug portion
    equals slugify_title(title, source_id), and the display portion equals
    the original title unchanged.

    **Validates: Requirements 1.1, 1.5, 1.6**
    """

    @given(title=titles, source_id=source_ids, artifact_type=artifact_types)
    @settings(max_examples=100)
    def test_rendered_link_matches_expected_format(
        self, title: str, source_id: str, artifact_type: str
    ) -> None:
        """Rendered link matches [[slug_Suffix|cleaned_title]] format."""
        link = WikiLink.from_source(title, source_id, artifact_type)
        rendered = link.render()

        expected_slug = slugify_title(title, source_id)
        expected_suffix = ARTIFACT_SUFFIXES[artifact_type]
        clean_title = title.replace("[", "").replace("]", "").strip()
        expected = f"[[{expected_slug}_{expected_suffix}|{clean_title}]]"

        assert rendered == expected

    @given(title=titles, source_id=source_ids, artifact_type=artifact_types)
    @settings(max_examples=100)
    def test_slug_portion_equals_slugify_title(
        self, title: str, source_id: str, artifact_type: str
    ) -> None:
        """The slug field of the WikiLink equals slugify_title(title, source_id)."""
        link = WikiLink.from_source(title, source_id, artifact_type)
        expected_slug = slugify_title(title, source_id)
        assert link.slug == expected_slug

    @given(title=titles, source_id=source_ids, artifact_type=artifact_types)
    @settings(max_examples=100)
    def test_display_portion_equals_cleaned_title(
        self, title: str, source_id: str, artifact_type: str
    ) -> None:
        """The display_title field equals the title with brackets removed and whitespace stripped."""
        link = WikiLink.from_source(title, source_id, artifact_type)
        expected = title.replace("[", "").replace("]", "").strip()
        assert link.display_title == expected


# ---------------------------------------------------------------------------
# Property 5: Link integrity detection
# Feature: living-wiki-0-7, Property 5: Link integrity detection
# ---------------------------------------------------------------------------

import tempfile
from pathlib import Path

from hypothesis import assume, HealthCheck

from distill.library.links import BrokenLink, check_links, fix_broken_links
from distill.library.paths import slugify_title


# Strategy for generating valid slugs (filesystem-safe identifiers)
valid_slugs = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=3,
    max_size=30,
).map(lambda s: slugify_title(s, ""))


# Strategy for generating display titles
display_titles = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
        blacklist_characters="\n\r[]|",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())


class TestLinkIntegrityDetection:
    """Property 5: Link integrity detection.

    For any corpus directory containing markdown files with wiki-links,
    `check_links` SHALL find every [[...]] pattern in every .md file,
    AND for each link, correctly classify it as broken (target file does
    not exist) or valid (target file exists), reporting the correct source
    file path and line number for broken links.

    **Validates: Requirements 3.1, 3.2**
    """

    @given(
        valid_slug_list=st.lists(valid_slugs, min_size=1, max_size=5, unique=True),
        broken_slug_list=st.lists(valid_slugs, min_size=1, max_size=5, unique=True),
        display_title=display_titles,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_check_links_finds_all_wiki_link_patterns(
        self,
        valid_slug_list: list[str],
        broken_slug_list: list[str],
        display_title: str,
    ) -> None:
        """check_links finds every [[...]] pattern in .md files."""
        # Ensure broken slugs don't overlap with valid slugs
        broken_slug_list = [s for s in broken_slug_list if s not in valid_slug_list]
        assume(len(broken_slug_list) > 0)

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)

            # Create valid artifact files (one per valid slug)
            for slug in valid_slug_list:
                (corpus / f"{slug}_Insights.md").write_text(
                    f"---\ntitle: {slug}\n---\nContent for {slug}\n",
                    encoding="utf-8",
                )

            # Create a markdown file with both valid and broken links
            lines = []
            for slug in valid_slug_list:
                lines.append(f"See [[{slug}_Insights|{display_title}]] for details.")
            for slug in broken_slug_list:
                lines.append(f"See [[{slug}_Missing|{display_title}]] for details.")

            (corpus / "index.md").write_text("\n".join(lines), encoding="utf-8")

            result = check_links(corpus)

            # Total links should equal valid + broken
            expected_total = len(valid_slug_list) + len(broken_slug_list)
            assert result.total_links == expected_total

    @given(
        valid_slug_list=st.lists(valid_slugs, min_size=1, max_size=5, unique=True),
        broken_slug_list=st.lists(valid_slugs, min_size=1, max_size=5, unique=True),
        display_title=display_titles,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_check_links_correctly_classifies_broken_vs_valid(
        self,
        valid_slug_list: list[str],
        broken_slug_list: list[str],
        display_title: str,
    ) -> None:
        """check_links correctly classifies broken vs valid links."""
        broken_slug_list = [s for s in broken_slug_list if s not in valid_slug_list]
        assume(len(broken_slug_list) > 0)

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)

            # Create valid artifact files
            for slug in valid_slug_list:
                (corpus / f"{slug}_Insights.md").write_text(
                    f"Content for {slug}\n", encoding="utf-8"
                )

            # Create a file with mixed links
            lines = []
            for slug in valid_slug_list:
                lines.append(f"Valid: [[{slug}_Insights|{display_title}]]")
            for slug in broken_slug_list:
                lines.append(f"Broken: [[{slug}_Missing|{display_title}]]")

            (corpus / "test_file.md").write_text("\n".join(lines), encoding="utf-8")

            result = check_links(corpus)

            # Only broken links should be reported
            assert len(result.broken_links) == len(broken_slug_list)

            # All broken links should reference the broken slugs
            broken_targets = {bl.target_slug for bl in result.broken_links}
            expected_broken = {f"{slug}_Missing" for slug in broken_slug_list}
            assert broken_targets == expected_broken

    @given(
        valid_slug_list=st.lists(valid_slugs, min_size=1, max_size=3, unique=True),
        broken_slug_list=st.lists(valid_slugs, min_size=1, max_size=3, unique=True),
        display_title=display_titles,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_check_links_reports_correct_line_numbers(
        self,
        valid_slug_list: list[str],
        broken_slug_list: list[str],
        display_title: str,
    ) -> None:
        """check_links reports correct source file path and line number for broken links."""
        broken_slug_list = [s for s in broken_slug_list if s not in valid_slug_list]
        assume(len(broken_slug_list) > 0)

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)

            # Create valid artifact files
            for slug in valid_slug_list:
                (corpus / f"{slug}_Insights.md").write_text(
                    f"Content for {slug}\n", encoding="utf-8"
                )

            # Create a file with broken links at known line numbers
            lines = ["# Header"]  # line 1
            for i, slug in enumerate(broken_slug_list):
                lines.append(f"Broken link {i}: [[{slug}_Missing|{display_title}]]")

            test_file = corpus / "source.md"
            test_file.write_text("\n".join(lines), encoding="utf-8")

            result = check_links(corpus)

            # Verify line numbers are correct (broken links start at line 2)
            for bl in result.broken_links:
                if bl.source_file == test_file:
                    assert bl.line_number >= 2
                    assert bl.source_file == test_file


# ---------------------------------------------------------------------------
# Property 6: Broken link fix preserves valid links
# Feature: living-wiki-0-7, Property 6: Broken link fix preserves valid links
# ---------------------------------------------------------------------------


class TestBrokenLinkFix:
    """Property 6: Broken link fix preserves valid links.

    For any markdown content containing a mix of valid and broken wiki-links,
    `fix_broken_links` SHALL replace only the broken links with plain-text
    citations while leaving all valid wiki-links unchanged.

    **Validates: Requirements 3.5**
    """

    @given(
        valid_slug_list=st.lists(valid_slugs, min_size=1, max_size=5, unique=True),
        broken_slug_list=st.lists(valid_slugs, min_size=1, max_size=5, unique=True),
        display_title=display_titles,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_fix_broken_links_replaces_only_broken_links(
        self,
        valid_slug_list: list[str],
        broken_slug_list: list[str],
        display_title: str,
    ) -> None:
        """fix_broken_links replaces only broken links, leaving valid ones unchanged."""
        broken_slug_list = [s for s in broken_slug_list if s not in valid_slug_list]
        assume(len(broken_slug_list) > 0)

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)

            # Create valid artifact files
            for slug in valid_slug_list:
                (corpus / f"{slug}_Insights.md").write_text(
                    f"Content for {slug}\n", encoding="utf-8"
                )

            # Create a file with mixed valid and broken links
            lines = []
            for slug in valid_slug_list:
                lines.append(f"Valid: [[{slug}_Insights|{display_title}]]")
            for slug in broken_slug_list:
                lines.append(f"Broken: [[{slug}_Missing|{display_title}]]")

            test_file = corpus / "mixed.md"
            test_file.write_text("\n".join(lines), encoding="utf-8")

            # Run check_links to find broken links
            result = check_links(corpus)
            assert len(result.broken_links) == len(broken_slug_list)

            # Fix the broken links
            fixed_count = fix_broken_links(corpus, result.broken_links)
            assert fixed_count == len(broken_slug_list)

            # Read the fixed content
            fixed_content = test_file.read_text(encoding="utf-8")

            # Valid links should still be present
            for slug in valid_slug_list:
                assert f"[[{slug}_Insights|{display_title}]]" in fixed_content

            # Broken links should be replaced with plain text
            for slug in broken_slug_list:
                assert f"[[{slug}_Missing|{display_title}]]" not in fixed_content
                # The display title should remain as plain text
                assert display_title in fixed_content

    @given(
        valid_slug_list=st.lists(valid_slugs, min_size=1, max_size=5, unique=True),
        broken_slug_list=st.lists(valid_slugs, min_size=1, max_size=5, unique=True),
        display_title=display_titles,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_fix_broken_links_preserves_valid_links_unchanged(
        self,
        valid_slug_list: list[str],
        broken_slug_list: list[str],
        display_title: str,
    ) -> None:
        """After fixing, valid wiki-links remain exactly as they were."""
        broken_slug_list = [s for s in broken_slug_list if s not in valid_slug_list]
        assume(len(broken_slug_list) > 0)

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)

            # Create valid artifact files
            for slug in valid_slug_list:
                (corpus / f"{slug}_Insights.md").write_text(
                    f"Content for {slug}\n", encoding="utf-8"
                )

            # Create a file with mixed links
            valid_links = [f"[[{slug}_Insights|{display_title}]]" for slug in valid_slug_list]
            broken_links = [f"[[{slug}_Missing|{display_title}]]" for slug in broken_slug_list]
            all_links = valid_links + broken_links

            test_file = corpus / "test.md"
            test_file.write_text("\n".join(all_links), encoding="utf-8")

            # Check and fix
            result = check_links(corpus)
            fix_broken_links(corpus, result.broken_links)

            # Read fixed content
            fixed_content = test_file.read_text(encoding="utf-8")

            # Count valid links still present
            valid_link_count = sum(1 for vl in valid_links if vl in fixed_content)
            assert valid_link_count == len(valid_links)

    @given(
        broken_slug_list=st.lists(valid_slugs, min_size=1, max_size=5, unique=True),
        display_title=display_titles,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_fix_broken_links_uses_display_title_as_replacement(
        self,
        broken_slug_list: list[str],
        display_title: str,
    ) -> None:
        """Broken links are replaced with their display title text."""
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)

            # Create a file with only broken links (no other text to avoid false matches)
            lines = [f"[[{slug}_Missing|{display_title}]]" for slug in broken_slug_list]
            test_file = corpus / "broken_only.md"
            test_file.write_text("\n".join(lines), encoding="utf-8")

            # Check and fix
            result = check_links(corpus)
            assert len(result.broken_links) == len(broken_slug_list)

            fix_broken_links(corpus, result.broken_links)

            # Read fixed content
            fixed_content = test_file.read_text(encoding="utf-8")

            # No wiki-links should remain
            import re

            remaining_links = re.findall(r"\[\[.*?\]\]", fixed_content)
            assert len(remaining_links) == 0

            # Each line should now just be the display title (stripped)
            fixed_lines = [l for l in fixed_content.splitlines() if l.strip()]
            for line in fixed_lines:
                assert line == display_title.strip()
