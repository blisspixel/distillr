"""Tests for OKF export and validation helpers."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from distill.config import DistillConfig
from distill.library.okf import (
    _display_path,
    _replace_output_dir,
    _rewrite_wikilinks,
    _tags_for,
    _type_for,
    _verify_sidecar_for,
    detect_okf_export_staleness,
    export_okf_bundle,
    okf_bundle_output_dir,
    validate_okf_bundle,
)


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
        llms = (result.output_dir / "llms.txt").read_text(encoding="utf-8")
        assert "index.md" in llms
        assert "log.md" in llms
        exported = result.output_dir / "videos" / "example" / "example_Insights.md"
        text = exported.read_text(encoding="utf-8")
        assert 'type: "Source Insight"' in text
        assert 'resource: "https://example.com/watch"' in text
        assert "Distill source artifact" in text

    def test_exports_concept_and_entity_playbook_types(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        _write(
            topic_dir / "concepts" / "rotational_embedding.md",
            "---\ntitle: Rotational Embedding\n---\n\n# Concept\n",
        )
        _write(
            topic_dir / "entities" / "openai.md",
            "---\ntitle: OpenAI\n---\n\n# Entity\n",
        )

        result = export_okf_bundle(config, "ai")
        concept = (result.output_dir / "concepts" / "rotational_embedding.md").read_text(
            encoding="utf-8"
        )
        entity = (result.output_dir / "entities" / "openai.md").read_text(encoding="utf-8")

        assert 'type: "Concept Playbook"' in concept
        assert 'type: "Entity Playbook"' in entity
        index = (result.output_dir / "index.md").read_text(encoding="utf-8")
        assert "## Concept Playbook" in index
        assert "## Entity Playbook" in index

    def test_rewrites_wikilinks_to_bundle_relative_markdown_links(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        _write(
            topic_dir / "videos" / "a" / "a_Insights.md",
            "---\ntitle: Alpha\n---\n\nSee [[b_Insights|Beta paper]].\n",
        )
        _write(
            topic_dir / "papers" / "b" / "b_Insights.md",
            "---\ntitle: Beta\n---\n\nBody.\n",
        )

        result = export_okf_bundle(config, "ai")
        alpha = (result.output_dir / "videos" / "a" / "a_Insights.md").read_text(encoding="utf-8")

        assert "[Beta paper](papers/b/b_Insights.md)" in alpha
        assert "[[b_Insights" not in alpha

    def test_log_includes_profile_run_history(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        _write(topic_dir / "ai_Topic_Synthesis.md", "# Synthesis\n")
        state_dir = config.library_dir / ".distill" / "profiles" / "vendor-docs-watch"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_dir.joinpath("run_state.json").write_text(
            json.dumps(
                {
                    "schema_version": "profile-run-state.v1",
                    "profile": "vendor-docs-watch",
                    "topic": "ai",
                    "attempts": [
                        {
                            "attempted_at": "2026-06-18T12:00:00Z",
                            "status": "succeeded",
                            "title": "Example feed item",
                            "key": "feed_item:1",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = export_okf_bundle(config, "ai")
        log = (result.output_dir / "log.md").read_text(encoding="utf-8")

        assert "Profile `vendor-docs-watch`: succeeded" in log

    def test_exports_all_topics_under_topic_directories(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        _write(config.topic_dir("ai") / "ai_Topic_Synthesis.md", "# AI\n")
        _write(config.topic_dir("security") / "security_Topic_Synthesis.md", "# Security\n")

        result = export_okf_bundle(config, "all")

        assert result.validation.ok
        assert (result.output_dir / "ai" / "ai_Topic_Synthesis.md").exists()
        assert (result.output_dir / "security" / "security_Topic_Synthesis.md").exists()


class TestValidateEdgeCases:
    def test_nonexistent_path_is_error(self, tmp_path: Path) -> None:
        result = validate_okf_bundle(tmp_path / "nope")
        assert not result.ok
        assert result.files_checked == 0
        assert any("does not exist" in e.message for e in result.errors)

    def test_path_that_is_a_file_is_error(self, tmp_path: Path) -> None:
        target = tmp_path / "f.md"
        target.write_text("x", encoding="utf-8")
        result = validate_okf_bundle(target)
        assert not result.ok
        assert any("not a directory" in e.message for e in result.errors)

    def test_missing_index_and_log_are_warnings_only(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "concept.md", "---\ntype: Concept\n---\n\n# C\n")
        result = validate_okf_bundle(bundle)
        assert result.ok  # warnings do not fail validation
        messages = [w.message for w in result.warnings]
        assert any("index.md" in m for m in messages)
        assert any("log.md" in m for m in messages)

    def test_reserved_file_unparseable_frontmatter_is_error(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "---\ntype: [broken\n---\n\n# x\n")
        _write(bundle / "log.md", "# Log\n")
        result = validate_okf_bundle(bundle)
        assert not result.ok
        assert any("not parseable" in e.message for e in result.errors)

    def test_non_mapping_frontmatter_is_error(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# I\n")
        _write(bundle / "log.md", "# L\n")
        _write(bundle / "concept.md", "---\njust a scalar\n---\n\n# C\n")
        result = validate_okf_bundle(bundle)
        assert not result.ok
        assert any("YAML mapping" in e.message for e in result.errors)

    def test_link_escaping_bundle_is_warning(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# I\n")
        _write(bundle / "log.md", "# L\n")
        _write(bundle / "sub" / "concept.md", "---\ntype: C\n---\n\n[up](../../outside.md)\n")
        result = validate_okf_bundle(bundle)
        assert any("escapes bundle" in w.message for w in result.warnings)

    def test_absolute_link_to_existing_file_is_not_broken(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# I\n")
        _write(bundle / "log.md", "# L\n")
        _write(bundle / "target.md", "---\ntype: T\n---\n\n# t\n")
        _write(bundle / "concept.md", "---\ntype: C\n---\n\n[t](/target.md)\n")
        result = validate_okf_bundle(bundle)
        assert not any("Broken" in w.message for w in result.warnings)

    def test_to_dict_carries_errors(self, tmp_path: Path) -> None:
        result = validate_okf_bundle(tmp_path / "nope")
        as_dict = result.to_dict()
        assert as_dict["ok"] is False
        assert as_dict["files_checked"] == 0
        assert as_dict["errors"][0]["severity"] == "error"

    def test_non_reserved_markdown_without_frontmatter_is_error(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# I\n")
        _write(bundle / "log.md", "# L\n")
        _write(bundle / "concept.md", "# No frontmatter here\n")
        result = validate_okf_bundle(bundle)
        assert not result.ok
        assert any("Missing YAML frontmatter" in e.message for e in result.errors)

    def test_external_anchor_and_nonmd_links_are_not_validated(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# I\n")
        _write(bundle / "log.md", "# L\n")
        _write(
            bundle / "concept.md",
            "---\ntype: C\n---\n\n[ext](https://example.com) [anchor](#s) [txt](notes.txt)\n",
        )
        result = validate_okf_bundle(bundle)
        assert result.ok
        assert result.warnings == ()  # external / anchor / non-md links are skipped


class TestExportEdgeCases:
    def test_missing_topic_raises(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        with pytest.raises(FileNotFoundError):
            export_okf_bundle(config, "does-not-exist")

    def test_render_includes_native_type_and_verify_sidecar(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        _write(
            topic_dir / "papers" / "p" / "p_Insights.md",
            "---\ntype: insights\nurl: https://x.test/a\n---\n\nBody.\n",
        )
        _write(topic_dir / "papers" / "p" / "p_Insights_Verify.json", "{}")

        result = export_okf_bundle(config, "ai")

        exported = (result.output_dir / "papers" / "p" / "p_Insights.md").read_text(
            encoding="utf-8"
        )
        assert 'native_type: "insights"' in exported  # dump quotes string values
        assert "verify_sidecar:" in exported
        assert "Verify sidecar:" in exported  # citation line

    def test_topic_without_concept_markdown_writes_empty_index(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        # Only reserved files exist in the source; the collector ignores them.
        _write(config.topic_dir("empty") / "index.md", "# pre-existing\n")
        result = export_okf_bundle(config, "empty")
        index_text = (result.output_dir / "index.md").read_text(encoding="utf-8")
        assert "No Markdown concepts" in index_text
        assert result.files_written == 3  # generated index.md + log.md + llms.txt

    def test_to_dict_round_trips(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        _write(config.topic_dir("ai") / "ai_Topic_Synthesis.md", "# x\n")
        as_dict = export_okf_bundle(config, "ai").to_dict()
        assert as_dict["topic"] == "ai"
        assert as_dict["files_written"] >= 1
        assert as_dict["validation"]["ok"] is True

    def test_replace_output_dir_refuses_path_outside_output(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        with pytest.raises(ValueError, match="Refusing to replace"):
            _replace_output_dir(config, outside)

    def test_export_excludes_reserved_and_dotfile_sources(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        _write(topic_dir / "real_Insights.md", "---\ntype: insights\n---\n\n# r\n")
        _write(topic_dir / "index.md", "# source index, ignored\n")
        _write(topic_dir / ".hidden" / "secret_Insights.md", "---\ntype: x\n---\n\n# s\n")

        result = export_okf_bundle(config, "ai")

        assert (result.output_dir / "real_Insights.md").exists()
        assert not (result.output_dir / ".hidden" / "secret_Insights.md").exists()


class TestTypeAndTagInference:
    def test_agents_and_claude_md_are_orientation(self) -> None:
        assert _type_for(Path("AGENTS.md"), {}) == "Agent Orientation"
        assert _type_for(Path("CLAUDE.md"), {}) == "Agent Orientation"

    def test_okf_type_override_wins(self) -> None:
        assert _type_for(Path("x_Insights.md"), {"okf_type": "Custom"}) == "Custom"

    def test_native_type_used_when_present(self) -> None:
        assert _type_for(Path("weird.md"), {"type": "report"}) == "report"

    @pytest.mark.parametrize(
        ("stem", "expected"),
        [
            ("x_Audit", "Audit Report"),
            ("topic_Synthesis", "Synthesis"),
            ("x_Report", "Report"),
            ("x_brief", "Brief"),
            ("x_Insights", "Source Insight"),
            ("x_Paper", "Source Receipt"),
            ("x_Content", "Source Receipt"),
            ("x_Transcript", "Source Receipt"),
        ],
    )
    def test_marker_based_types(self, stem: str, expected: str) -> None:
        assert _type_for(Path(f"{stem}.md"), {}) == expected

    def test_unknown_stem_falls_back_to_distill_artifact(self) -> None:
        assert _type_for(Path("random.md"), {}) == "Distill Artifact"

    def test_concepts_and_entities_dirs_override_stem_inference(self) -> None:
        assert _type_for(Path("foo.md"), {}, rel_path=Path("concepts/foo.md")) == "Concept Playbook"
        assert _type_for(Path("bar.md"), {}, rel_path=Path("entities/bar.md")) == "Entity Playbook"

    def test_tags_parse_list_style_and_topic(self) -> None:
        tags = _tags_for(
            "ai", {"tags": '["distill/ai", "cs.AI"]', "source": "arxiv"}, "Source Insight"
        )
        assert "distill" in tags
        assert "source-insight" in tags
        assert "topic:ai" in tags
        assert "distill/ai" in tags
        assert "cs.AI" in tags
        assert "arxiv" in tags

    def test_tags_for_all_topic_omits_topic_tag(self) -> None:
        tags = _tags_for("all", {}, "Synthesis")
        assert not any(t.startswith("topic:") for t in tags)


class TestWikilinkRewrite:
    def test_rewrites_known_target(self) -> None:
        body = "See [[target_Insights|Target title]] for detail."
        rewritten = _rewrite_wikilinks(body, {"target_Insights": "papers/t/target_Insights.md"})
        assert rewritten == "See [Target title](papers/t/target_Insights.md) for detail."

    def test_unknown_target_degrades_to_plain_text(self) -> None:
        body = "See [[missing_Insights]] for detail."
        rewritten = _rewrite_wikilinks(body, {})
        assert rewritten == "See missing Insights for detail."


class TestSmallHelpers:
    def test_verify_sidecar_for_finds_sibling(self, tmp_path: Path) -> None:
        source = tmp_path / "x_Insights.md"
        source.write_text("x", encoding="utf-8")
        sidecar = tmp_path / "x_Insights_Verify.json"
        sidecar.write_text("{}", encoding="utf-8")
        assert _verify_sidecar_for(source) == sidecar

    def test_verify_sidecar_for_none_when_absent(self, tmp_path: Path) -> None:
        source = tmp_path / "x_Insights.md"
        source.write_text("x", encoding="utf-8")
        assert _verify_sidecar_for(source) is None

    def test_display_path_outside_root_returns_str(self, tmp_path: Path) -> None:
        other = tmp_path / "other" / "f.md"
        root = tmp_path / "root"
        assert _display_path(root, other) == str(other)


class TestOkfExportStaleness:
    def test_okf_bundle_output_dir_uses_sanitized_topic(self, tmp_path: Path) -> None:
        library = tmp_path / "library"
        assert okf_bundle_output_dir(library, "AI News") == tmp_path / "output" / "okf-AI News"
        assert okf_bundle_output_dir(library, "../../etc") == tmp_path / "output" / "okf-etc"

    def test_detect_staleness_when_native_corpus_is_newer(self, tmp_path: Path) -> None:
        library = tmp_path / "library"
        topic_dir = library / "topics" / "ai"
        bundle_dir = tmp_path / "output" / "okf-ai"
        _write(topic_dir / "fresh.md", "# fresh\n")
        _write(bundle_dir / "index.md", "---\n---\n")
        _write(bundle_dir / "log.md", "---\n---\n")
        old = time.time() - 100
        for path in (bundle_dir / "index.md", bundle_dir / "log.md"):
            os.utime(path, (old, old))

        result = detect_okf_export_staleness(library, "ai")

        assert result is not None
        assert result.bundle_dir == bundle_dir

    def test_detect_staleness_none_when_bundle_missing(self, tmp_path: Path) -> None:
        library = tmp_path / "library"
        _write(library / "topics" / "ai" / "x.md", "# x\n")
        assert detect_okf_export_staleness(library, "ai") is None

    def test_detect_staleness_none_when_bundle_is_current(self, tmp_path: Path) -> None:
        library = tmp_path / "library"
        topic_dir = library / "topics" / "ai"
        bundle_dir = tmp_path / "output" / "okf-ai"
        _write(topic_dir / "x.md", "# x\n")
        _write(bundle_dir / "index.md", "---\n---\n")
        _write(bundle_dir / "log.md", "---\n---\n")
        now = time.time() + 100
        for path in (bundle_dir / "index.md", bundle_dir / "log.md"):
            os.utime(path, (now, now))

        assert detect_okf_export_staleness(library, "ai") is None
