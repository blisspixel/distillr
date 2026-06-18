"""Tests for OKF export and validation helpers."""

from __future__ import annotations

from pathlib import Path

from distill.config import DistillConfig
from distill.library.okf import export_okf_bundle, validate_okf_bundle


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestValidateOkfBundle:
    def test_accepts_valid_bundle(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(
            bundle / "index.md",
            "---\ntitle: Test\n---\n\n# Index\n\n- [Concept](concepts/item.md)\n",
        )
        _write(bundle / "log.md", "# Log\n")
        _write(bundle / "concepts" / "item.md", "---\ntype: Concept\n---\n\n# Item\n")

        result = validate_okf_bundle(bundle)

        assert result.ok
        assert result.files_checked == 3
        assert result.errors == ()

    def test_requires_type_on_non_reserved_markdown(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# Index\n")
        _write(bundle / "log.md", "# Log\n")
        _write(bundle / "concept.md", "---\ntitle: Missing type\n---\n\n# Concept\n")

        result = validate_okf_bundle(bundle)

        assert not result.ok
        assert any("type" in issue.message for issue in result.errors)

    def test_bad_yaml_is_an_error(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# Index\n")
        _write(bundle / "log.md", "# Log\n")
        _write(bundle / "concept.md", "---\ntype: [broken\n---\n\n# Concept\n")

        result = validate_okf_bundle(bundle)

        assert not result.ok
        assert any("Invalid YAML" in issue.message for issue in result.errors)

    def test_broken_markdown_link_is_warning(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# Index\n")
        _write(bundle / "log.md", "# Log\n")
        _write(
            bundle / "concept.md",
            "---\ntype: Concept\n---\n\nSee [Missing](missing.md).\n",
        )

        result = validate_okf_bundle(bundle)

        assert result.ok
        assert any("Broken Markdown link" in issue.message for issue in result.warnings)


class TestExportOkfBundle:
    def test_exports_topic_markdown_as_valid_okf(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        _write(
            topic_dir / "videos" / "example" / "example_Insights.md",
            "---\nvideo_title: Test Video\nurl: https://example.com/watch\n---\n\n# Insight\nBody.\n",
        )
        _write(topic_dir / "ai_Topic_Synthesis.md", "# Synthesis\n")

        result = export_okf_bundle(config, "ai")

        assert result.validation.ok
        assert result.output_dir == tmp_path / "output" / "okf-ai"
        assert (result.output_dir / "index.md").exists()
        assert (result.output_dir / "log.md").exists()
        exported = result.output_dir / "videos" / "example" / "example_Insights.md"
        text = exported.read_text(encoding="utf-8")
        assert 'type: "Source Insight"' in text
        assert 'resource: "https://example.com/watch"' in text
        assert "Distill source artifact" in text

    def test_exports_all_topics_under_topic_directories(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        _write(config.topic_dir("ai") / "ai_Topic_Synthesis.md", "# AI\n")
        _write(config.topic_dir("security") / "security_Topic_Synthesis.md", "# Security\n")

        result = export_okf_bundle(config, "all")

        assert result.validation.ok
        assert (result.output_dir / "ai" / "ai_Topic_Synthesis.md").exists()
        assert (result.output_dir / "security" / "security_Topic_Synthesis.md").exists()
