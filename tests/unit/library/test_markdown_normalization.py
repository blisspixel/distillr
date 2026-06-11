"""Tests for bold-wrapped heading normalization on the markdown-artifact funnel.

Dogfood catch (2026-06-11): grok-4.3 emitted every synthesis section heading as
``**## Cross-Paper Claims**``, which renders as literal bold text instead of a
heading in Obsidian and on GitHub. The funnel unwraps that class
deterministically at write time.
"""

from distill.library.paths import normalize_markdown_headings, write_markdown_artifact


class TestNormalizeMarkdownHeadings:
    def test_unwraps_bold_wrapped_heading(self):
        assert normalize_markdown_headings("**## Cross-Paper Claims**") == "## Cross-Paper Claims"

    def test_unwraps_all_heading_levels_and_preserves_indent(self):
        text = "**# H1**\n  **### H3 with words**  "
        assert normalize_markdown_headings(text) == "# H1\n  ### H3 with words"

    def test_plain_heading_untouched(self):
        assert normalize_markdown_headings("## Plain") == "## Plain"

    def test_bold_inside_heading_is_valid_and_untouched(self):
        assert normalize_markdown_headings("## **Emphasis** inside") == "## **Emphasis** inside"

    def test_bold_prose_untouched(self):
        assert normalize_markdown_headings("**not a heading**") == "**not a heading**"

    def test_bold_mid_line_untouched(self):
        text = "intro **## looks bold** outro"
        assert normalize_markdown_headings(text) == text

    def test_fenced_code_blocks_left_alone(self):
        text = "```\n**## inside fence**\n```\n**## outside fence**"
        assert (
            normalize_markdown_headings(text) == "```\n**## inside fence**\n```\n## outside fence"
        )

    def test_hash_without_space_is_not_a_heading(self):
        # ``**#hashtag**`` is bold prose, not an ATX heading.
        assert normalize_markdown_headings("**#hashtag**") == "**#hashtag**"


def test_write_markdown_artifact_normalizes_headings(tmp_path):
    path = write_markdown_artifact(tmp_path, "insights", "**## Section**\n\nbody", identity="x")
    assert path.read_text(encoding="utf-8").startswith("## Section")
