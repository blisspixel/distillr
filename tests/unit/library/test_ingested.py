"""Tests for distill.library.ingested (already-ingested identity walk)."""

from distill.library.ingested import ingested_source_ids, normalize_arxiv_id


def _write_insight(path, frontmatter_lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(["---", *frontmatter_lines, "---", "", "content"])
    path.write_text(body, encoding="utf-8")


class TestNormalizeArxivId:
    def test_strips_new_style_version_suffix(self):
        assert normalize_arxiv_id("2604.11544v2") == "2604.11544"

    def test_versionless_new_style_unchanged(self):
        assert normalize_arxiv_id("2604.11544") == "2604.11544"

    def test_strips_old_style_version_suffix(self):
        assert normalize_arxiv_id("cs/0123456v1") == "cs/0123456"

    def test_youtube_id_passes_through_case_preserved(self):
        # Video ids are case-sensitive; a blanket lowercase would corrupt them.
        assert normalize_arxiv_id("AbC-123xyZ") == "AbC-123xyZ"

    def test_strips_surrounding_whitespace(self):
        assert normalize_arxiv_id("  2604.11544v1 ") == "2604.11544"


class TestIngestedSourceIds:
    def test_missing_topic_dir_is_empty(self, tmp_path):
        assert ingested_source_ids(tmp_path / "nope") == frozenset()

    def test_collects_paper_video_and_page_ids(self, tmp_path):
        topic = tmp_path / "topic"
        _write_insight(topic / "papers" / "p" / "p_Insights.md", ['paper_id: "2604.11544v1"'])
        _write_insight(
            topic / "channels" / "c" / "videos" / "v" / "v_Insights.md",
            ['video_id: "AbC123"'],
        )
        _write_insight(
            topic / "sites" / "h" / "pages" / "pg" / "pg_Insights.md",
            ['page_id: "docs-page"'],
        )

        ids = ingested_source_ids(topic)

        # Paper id is present raw AND version-stripped so a v2 search hit matches.
        assert "2604.11544v1" in ids
        assert "2604.11544" in ids
        assert "AbC123" in ids
        assert "docs-page" in ids

    def test_falls_back_to_directory_slug_without_id_frontmatter(self, tmp_path):
        topic = tmp_path / "topic"
        _write_insight(topic / "papers" / "mystery_paper" / "x_Insights.md", ["title: x"])

        assert "mystery_paper" in ingested_source_ids(topic)

    def test_skips_derived_artifact_subtrees(self, tmp_path):
        topic = tmp_path / "topic"
        _write_insight(topic / "concepts" / "c" / "c_Insights.md", ['source_id: "derived"'])
        _write_insight(topic / ".history" / "h" / "h_Insights.md", ['source_id: "hist"'])

        assert ingested_source_ids(topic) == frozenset()
