"""Tests for OKF export and validation helpers."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import distill.library.okf as okf_module
import distill.library.okf_v02 as okf_v02_module
from distill.config import DistillConfig
from distill.library.insights import insight_content_sha256
from distill.library.okf import (
    OkfValidationLimits,
    _display_path,
    _publish_staged_output,
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
    @pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf"), "1"])
    def test_validation_limits_reject_invalid_timeout(self, timeout: object) -> None:
        with pytest.raises(ValueError, match="timeout"):
            OkfValidationLimits(timeout_seconds=timeout)  # type: ignore[arg-type] - runtime validator receives invalid values

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

    def test_accepts_valid_v02_trust_provenance_and_lifecycle_fields(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", '---\nokf_version: "0.2"\n---\n\n# Index\n')
        _write(bundle / "log.md", "# Directory Update Log\n\n## 2026-08-12\n\n* Updated.\n")
        _write(
            bundle / "concept.md",
            "---\n"
            "type: Reference\n"
            "generated: {by: distillr/1.0.0, at: 2026-08-12T10:00:00Z}\n"
            "verified: {by: process:distill-verify, at: 2026-08-12T10:01:00Z}\n"
            "sources: [{id: source, resource: https://example.com}]\n"
            "status: stable\n"
            "stale_after: 2026-12-31\n"
            "---\n\n# Concept\n",
        )

        result = validate_okf_bundle(bundle)

        assert result.ok
        assert result.warnings == ()

    def test_v02_optional_family_shape_problems_are_warnings(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# Index\n")
        _write(bundle / "log.md", "# Directory Update Log\n")
        _write(
            bundle / "concept.md",
            "---\n"
            "type: Reference\n"
            "generated: {at: yesterday}\n"
            "verified: [{by: process:x}]\n"
            "sources: [{title: Missing resource}]\n"
            "status: unknown\n"
            "stale_after: P7D\n"
            "---\n",
        )

        result = validate_okf_bundle(bundle)

        assert result.ok
        messages = [issue.message for issue in result.warnings]
        assert any("generated" in message for message in messages)
        assert any("verified" in message for message in messages)
        assert any("sources" in message for message in messages)
        assert any("status" in message for message in messages)
        assert any("stale_after" in message for message in messages)

    def test_attested_computation_requires_runtime(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "concept.md", "---\ntype: Attested Computation\n---\n")

        result = validate_okf_bundle(bundle)

        assert not result.ok
        assert any("runtime" in issue.message for issue in result.errors)

    def test_log_entries_require_iso_date_groups(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "log.md", "# Directory Update Log\n\n* Ungrouped update.\n")

        result = validate_okf_bundle(bundle)

        assert not result.ok
        assert any("ISO date headings" in issue.message for issue in result.errors)

    def test_v02_reserved_and_family_edge_shapes_are_reported(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", '---\nokf_version: "0.1"\n---\n\n# Index\n')
        _write(
            bundle / "nested" / "index.md",
            '---\nokf_version: "0.2"\n---\n\n# Nested index\n',
        )
        _write(
            bundle / "log.md",
            "---\ntitle: Legacy\n---\n\n# Directory Update Log\n\n## not-a-date\n",
        )
        _write(
            bundle / "concept.md",
            "---\n"
            "type: Attested Computation\n"
            "runtime: python\n"
            "generated: []\n"
            "verified: {by: process:test, at: not-a-date}\n"
            'stale_after: "2026-02-31"\n'
            "---\n",
        )

        result = validate_okf_bundle(bundle)

        assert not result.ok
        messages = [issue.message for issue in (*result.errors, *result.warnings)]
        assert any("targets 0.2" in message for message in messages)
        assert any("bundle-root index" in message for message in messages)
        assert any("log.md should not have frontmatter" in message for message in messages)
        assert any("non-date section" in message for message in messages)
        assert any("generated" in message for message in messages)
        assert any("verified" in message for message in messages)
        assert any("stale_after" in message for message in messages)
        assert not any("must include runtime" in message for message in messages)

    def test_invalid_yaml_timestamp_is_an_error_instead_of_crashing(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "concept.md", "---\ntype: Reference\nstale_after: 2026-02-31\n---\n")

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

    def test_file_count_budget_stops_before_parsing_tree(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        for index in range(3):
            _write(bundle / f"concept-{index}.md", "---\ntype: Concept\n---\n")

        result = validate_okf_bundle(bundle, limits=OkfValidationLimits(max_files=2))

        assert not result.ok
        assert result.files_checked == 0
        assert any("file limit exceeded" in issue.message for issue in result.errors)

    def test_per_file_byte_budget_stops_before_read(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "concept.md", "---\ntype: Concept\n---\n" + "x" * 128)

        result = validate_okf_bundle(
            bundle,
            limits=OkfValidationLimits(max_file_bytes=64),
        )

        assert not result.ok
        assert result.files_checked == 0
        assert any("per-file byte limit" in issue.message for issue in result.errors)

    def test_aggregate_byte_budget_stops_before_read(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "a.md", "---\ntype: A\n---\n")
        _write(bundle / "b.md", "---\ntype: B\n---\n")

        result = validate_okf_bundle(
            bundle,
            limits=OkfValidationLimits(max_file_bytes=100, max_total_bytes=30),
        )

        assert not result.ok
        assert result.files_checked == 0
        assert any("aggregate byte limit" in issue.message for issue in result.errors)

    def test_tree_depth_budget_stops_nested_walk(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "a" / "b" / "c" / "concept.md", "---\ntype: C\n---\n")

        result = validate_okf_bundle(
            bundle,
            limits=OkfValidationLimits(max_tree_depth=2),
        )

        assert not result.ok
        assert any("tree depth" in issue.message for issue in result.errors)

    def test_monotonic_deadline_stops_walk(self, tmp_path: Path, monkeypatch) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "concept.md", "---\ntype: C\n---\n")
        ticks = iter((0.0, 2.0))
        monkeypatch.setattr(okf_module.time, "monotonic", lambda: next(ticks, 2.0))

        result = validate_okf_bundle(
            bundle,
            limits=OkfValidationLimits(timeout_seconds=1.0),
        )

        assert not result.ok
        assert any("deadline exceeded" in issue.message for issue in result.errors)

    def test_yaml_depth_budget_rejects_nested_frontmatter(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(
            bundle / "concept.md",
            "---\ntype: Concept\na:\n  b:\n    c:\n      d: value\n---\n",
        )

        result = validate_okf_bundle(
            bundle,
            limits=OkfValidationLimits(max_yaml_depth=3),
        )

        assert not result.ok
        assert any("YAML nesting exceeds" in issue.message for issue in result.errors)


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
        assert "Native Distill artifact" in text
        assert 'generated: {"at":' in text
        assert 'sources: [{"id": "source-url"' in text
        assert "timestamp:" not in text
        assert "# Citations" not in text
        index = (result.output_dir / "index.md").read_text(encoding="utf-8")
        assert 'okf_version: "0.2"' in index

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

    def test_log_uses_strict_bounded_cost_rows_and_structured_topic(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        _write(config.topic_dir("ai") / "ai_Topic_Synthesis.md", "# Synthesis\n")
        cost_log = config.library_dir / ".distill" / "cost_log.jsonl"
        _write(
            cost_log,
            "\n".join(
                [
                    '{"timestamp":"2026-06-18T10:00:00Z","command":"bad","n":NaN}',
                    '{"timestamp":"2026-06-18T11:00:00Z","command":"huge","n":' + "9" * 5000 + "}",
                    json.dumps(
                        {
                            "timestamp": "2026-06-18T12:00:00Z",
                            "command": "ingest",
                            "metadata": {"topic": "ai"},
                        }
                    ),
                ]
            ),
        )

        result = export_okf_bundle(config, "ai")
        log = (result.output_dir / "log.md").read_text(encoding="utf-8")

        assert "Cost log: ingest" in log
        assert "Cost log: bad" not in log
        assert "Cost log: huge" not in log

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

    def test_unreadable_root_is_reported_without_traversal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        original_lstat = Path.lstat

        def guarded_lstat(path: Path):
            if path == bundle:
                raise OSError("unreadable")
            return original_lstat(path)

        monkeypatch.setattr(Path, "lstat", guarded_lstat)

        result = validate_okf_bundle(bundle)

        assert result.files_checked == 0
        assert [issue.message for issue in result.errors] == ["Bundle path is unreadable"]

    def test_entry_budget_and_scan_failures_are_visible(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# Index\n")
        _write(bundle / "log.md", "# Log\n")
        _write(bundle / "concept.md", "---\ntype: Concept\n---\n")

        limited = validate_okf_bundle(bundle, limits=OkfValidationLimits(max_entries=1))
        assert any("entry limit exceeded" in issue.message for issue in limited.errors)

        monkeypatch.setattr(
            okf_module.os,
            "scandir",
            lambda _path: (_ for _ in ()).throw(OSError("scan failed")),
        )
        unreadable = validate_okf_bundle(bundle)
        assert any("Cannot scan bundle directory" in issue.message for issue in unreadable.errors)

    def test_validation_deadline_and_unsafe_read_are_visible(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle = tmp_path / "bundle"
        concept = bundle / "concept.md"
        _write(concept, "---\ntype: Concept\n---\n")
        monkeypatch.setattr(
            okf_module,
            "_bounded_okf_markdown_files",
            lambda *_args: ([concept], None),
        )
        ticks = iter((0.0, 2.0))
        monkeypatch.setattr(okf_module.time, "monotonic", lambda: next(ticks, 2.0))

        expired = validate_okf_bundle(bundle, limits=OkfValidationLimits(timeout_seconds=1))
        assert any("deadline exceeded" in issue.message for issue in expired.errors)

        monkeypatch.setattr(okf_module.time, "monotonic", lambda: 0.0)
        monkeypatch.setattr(okf_module, "read_confined_text", lambda *_args, **_kwargs: None)
        unreadable = validate_okf_bundle(bundle)
        assert any("unsafe or unreadable" in issue.message for issue in unreadable.errors)

    def test_link_and_issue_budgets_stop_validation(self, tmp_path: Path) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# Index\n")
        _write(bundle / "log.md", "# Log\n")
        _write(
            bundle / "concept.md",
            "---\ntype: Concept\n---\n\n[a](a.md) [b](b.md)\n",
        )

        links = validate_okf_bundle(bundle, limits=OkfValidationLimits(max_links_per_file=1))
        assert any("link limit exceeded" in issue.message for issue in links.errors)

        issues = validate_okf_bundle(bundle, limits=OkfValidationLimits(max_issues=1))
        assert any("issue limit exceeded" in issue.message for issue in issues.errors)

        direct = okf_module._collect_link_warnings(
            bundle,
            bundle / "concept.md",
            "[a](a.md)",
            [],
            max_links=1,
            max_issues=10,
            deadline=-1,
        )
        assert direct == "OKF validation deadline exceeded"

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

    @pytest.mark.parametrize(
        "target",
        [
            r"\\server\share.md",
            r"%5C%5Cserver%5Cshare.md",
            r"C:%5Coutside.md",
            r"folder%5Coutside.md",
        ],
    )
    def test_link_rejects_cross_platform_remote_or_drive_syntax(
        self,
        tmp_path: Path,
        target: str,
    ) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# I\n")
        _write(bundle / "log.md", "# L\n")
        _write(
            bundle / "concept.md",
            f"---\ntype: C\n---\n\n[remote]({target})\n",
        )

        result = validate_okf_bundle(bundle)

        assert any("escapes bundle" in warning.message for warning in result.warnings)

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

    def test_nested_markdown_symlink_is_rejected_without_reading_target(
        self, tmp_path: Path
    ) -> None:
        bundle = tmp_path / "bundle"
        _write(bundle / "index.md", "# I\n")
        _write(bundle / "log.md", "# L\n")
        outside = tmp_path / "outside.md"
        outside.write_text("private outside content", encoding="utf-8")
        linked = bundle / "concept.md"
        try:
            linked.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        result = validate_okf_bundle(bundle)

        assert not result.ok
        assert any("symbolic link" in issue.message for issue in result.errors)
        assert all("private outside content" not in issue.message for issue in result.errors)

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

    def test_render_preserves_invalid_sidecar_without_claiming_verification(
        self, tmp_path: Path
    ) -> None:
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
        assert 'distill_verification: {"receipt":' in exported
        assert '"status": "invalid"' in exported
        assert "verified:" not in exported
        assert "Verification receipt:" in exported
        copied = result.output_dir / "papers" / "p" / "p_Insights_Verify.json"
        assert copied.read_text(encoding="utf-8") == "{}"
        assert result.files_written == 5

    def test_clean_bound_sidecar_projects_machine_verification(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        insight = topic_dir / "local" / "doc" / "doc_Insights.md"
        receipt = insight.with_name("doc_Content.txt")
        _write(
            insight,
            "---\n"
            "type: insights\n"
            "source_receipt: doc_Content.txt\n"
            "generated_at: 2026-08-11T09:00:00Z\n"
            "model: model-test\n"
            "status: stable\n"
            "stale_after: 2026-12-31\n"
            "---\n\nBody 42.\n",
        )
        _write(receipt, "Receipt 42.\n")
        payload = {
            "schema_version": 3,
            "mode": "warn",
            "checked": 1,
            "supported": 1,
            "unsupported": [],
            "insight": insight.name,
            "source": receipt.name,
            "generated_at": "2026-08-12T10:00:00Z",
            "insight_sha256": insight_content_sha256(insight.read_text(encoding="utf-8")),
        }
        _write(insight.with_name("doc_Insights_Verify.json"), json.dumps(payload))

        result = export_okf_bundle(config, "ai")

        exported = (result.output_dir / "local" / "doc" / insight.name).read_text(encoding="utf-8")
        assert 'verified: [{"at": "2026-08-12T10:00:00Z"' in exported
        assert '"by": "process:distill-verify"' in exported
        assert '"status": "passed"' in exported
        assert 'native_generated_at: "2026-08-11T09:00:00Z"' in exported
        assert 'native_model: "model-test"' in exported
        assert 'status: "stable"' in exported
        assert 'stale_after: "2026-12-31"' in exported
        assert '"resource": "/local/doc/doc_Content.txt"' in exported
        assert (result.output_dir / "local" / "doc" / receipt.name).read_text(
            encoding="utf-8"
        ) == "Receipt 42.\n"

    def test_flagged_sidecar_never_projects_verified(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        insight = config.topic_dir("ai") / "doc_Insights.md"
        _write(insight, "Body 99.\n")
        payload = {
            "schema_version": 3,
            "mode": "warn",
            "checked": 1,
            "supported": 0,
            "unsupported": [{"token": "99", "kind": "integer", "context": "Body 99."}],
            "insight": insight.name,
            "source": "receipt.txt",
            "generated_at": "2026-08-12T10:00:00Z",
            "insight_sha256": insight_content_sha256(insight.read_text(encoding="utf-8")),
        }
        _write(insight.with_name("doc_Insights_Verify.json"), json.dumps(payload))

        result = export_okf_bundle(config, "ai")

        exported = (result.output_dir / insight.name).read_text(encoding="utf-8")
        assert '"status": "flagged"' in exported
        assert "verified:" not in exported

    def test_stale_digest_sidecar_is_unbound_and_never_verified(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        insight = config.topic_dir("ai") / "doc_Insights.md"
        _write(insight, "Current body 42.\n")
        payload = {
            "schema_version": 3,
            "mode": "warn",
            "checked": 1,
            "supported": 1,
            "unsupported": [],
            "insight": insight.name,
            "source": "receipt.txt",
            "generated_at": "2026-08-12T10:00:00Z",
            "insight_sha256": "0" * 64,
        }
        _write(insight.with_name("doc_Insights_Verify.json"), json.dumps(payload))

        result = export_okf_bundle(config, "ai")

        exported = (result.output_dir / insight.name).read_text(encoding="utf-8")
        assert '"status": "unbound"' in exported
        assert "verified:" not in exported

    @pytest.mark.parametrize(
        ("sidecar_text", "expected_status"),
        [
            ("[", "invalid"),
            ("[]", "invalid"),
            (
                json.dumps(
                    {
                        "schema_version": 3,
                        "mode": "warn",
                        "checked": 0,
                        "supported": 0,
                        "unsupported": [],
                        "insight": "doc_Insights.md",
                        "source": "receipt.txt",
                        "generated_at": "2026-08-12T10:00:00Z",
                    }
                ),
                "incomplete",
            ),
        ],
    )
    def test_unusable_sidecars_remain_receipts(
        self,
        tmp_path: Path,
        sidecar_text: str,
        expected_status: str,
    ) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        insight = config.topic_dir("ai") / "doc_Insights.md"
        _write(insight, "Body.\n")
        _write(insight.with_name("doc_Insights_Verify.json"), sidecar_text)

        result = export_okf_bundle(config, "ai")

        exported = (result.output_dir / insight.name).read_text(encoding="utf-8")
        assert f'"status": "{expected_status}"' in exported
        assert "verified:" not in exported

    def test_clean_bound_sidecar_with_invalid_time_is_not_verified(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        insight = config.topic_dir("ai") / "doc_Insights.md"
        _write(insight, "Body 42.\n")
        payload = {
            "schema_version": 3,
            "mode": "warn",
            "checked": 1,
            "supported": 1,
            "unsupported": [],
            "insight": insight.name,
            "source": "receipt.txt",
            "generated_at": "not-a-date",
            "insight_sha256": insight_content_sha256(insight.read_text(encoding="utf-8")),
        }
        _write(insight.with_name("doc_Insights_Verify.json"), json.dumps(payload))

        result = export_okf_bundle(config, "ai")

        exported = (result.output_dir / insight.name).read_text(encoding="utf-8")
        assert '"status": "invalid"' in exported
        assert "verified:" not in exported

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
        with pytest.raises(ValueError, match="Refusing output outside"):
            _replace_output_dir(config, outside)

    def test_replace_output_dir_refuses_output_parent(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        output_parent = config.library_dir.parent / "output"
        output_parent.mkdir(parents=True)

        with pytest.raises(ValueError, match="Refusing output outside"):
            _replace_output_dir(config, output_parent)

    def test_replace_output_dir_removes_only_the_validated_existing_bundle(
        self, tmp_path: Path
    ) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        output = okf_bundle_output_dir(config.library_dir, "ai")
        _write(output / "old.txt", "old")

        _replace_output_dir(config, output)

        assert output.is_dir()
        assert not (output / "old.txt").exists()

    def test_publish_staged_output_replaces_prior_bundle_and_cleans_backup(
        self, tmp_path: Path
    ) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        output = okf_bundle_output_dir(config.library_dir, "ai")
        staging = output.with_name(".okf-ai.staging-test")
        _write(output / "prior.txt", "prior")
        _write(staging / "current.txt", "current")

        _publish_staged_output(config, staging, output)

        assert (output / "current.txt").read_text(encoding="utf-8") == "current"
        assert not (output / "prior.txt").exists()
        assert not output.with_name(".okf-ai.previous").exists()

    def test_publish_staged_output_rolls_back_prior_bundle_on_rename_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        output = okf_bundle_output_dir(config.library_dir, "ai")
        staging = output.with_name(".okf-ai.staging-test")
        _write(output / "prior.txt", "prior")
        _write(staging / "current.txt", "current")
        original_rename = Path.rename

        def guarded_rename(path: Path, target: Path):
            if path == staging:
                raise OSError("publish failed")
            return original_rename(path, target)

        monkeypatch.setattr(Path, "rename", guarded_rename)

        with pytest.raises(OSError, match="publish failed"):
            _publish_staged_output(config, staging, output)

        assert (output / "prior.txt").read_text(encoding="utf-8") == "prior"
        assert (staging / "current.txt").read_text(encoding="utf-8") == "current"

    def test_publish_staged_output_refuses_unvalidated_staging(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        output = okf_bundle_output_dir(config.library_dir, "ai")
        staging = output.with_name(".okf-ai.staging-test")
        _write(staging / "current.txt", "current")
        monkeypatch.setattr(okf_module, "validate_confined_path", lambda *_args, **_kwargs: None)

        with pytest.raises(ValueError, match="unsafe staging"):
            _publish_staged_output(config, staging, output)

    def test_export_excludes_reserved_and_dotfile_sources(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        _write(topic_dir / "real_Insights.md", "---\ntype: insights\n---\n\n# r\n")
        _write(topic_dir / "index.md", "# source index, ignored\n")
        _write(topic_dir / ".hidden" / "secret_Insights.md", "---\ntype: x\n---\n\n# s\n")

        result = export_okf_bundle(config, "ai")

        assert (result.output_dir / "real_Insights.md").exists()
        assert not (result.output_dir / ".hidden" / "secret_Insights.md").exists()

    def test_export_rejects_symlinked_source_without_replacing_prior_output(
        self, tmp_path: Path
    ) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        outside = tmp_path / "outside.md"
        outside.write_text("private outside content", encoding="utf-8")
        linked = topic_dir / "concepts" / "leak.md"
        linked.parent.mkdir(parents=True)
        try:
            linked.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        prior_output = okf_bundle_output_dir(config.library_dir, "ai")
        marker = prior_output / "existing.txt"
        _write(marker, "preserve me")

        with pytest.raises(ValueError, match="unsafe OKF source"):
            export_okf_bundle(config, "ai")

        assert marker.read_text(encoding="utf-8") == "preserve me"
        assert not (prior_output / "concepts" / "leak.md").exists()

    def test_export_rejects_symlinked_verification_sidecar(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        insight = config.topic_dir("ai") / "doc_Insights.md"
        _write(insight, "Body.\n")
        outside = tmp_path / "outside.json"
        _write(outside, "{}")
        sidecar = insight.with_name("doc_Insights_Verify.json")
        try:
            sidecar.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        with pytest.raises(ValueError, match="unsafe OKF verification sidecar"):
            export_okf_bundle(config, "ai")

    def test_export_rejects_unreadable_verification_sidecar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        insight = config.topic_dir("ai") / "doc_Insights.md"
        sidecar = insight.with_name("doc_Insights_Verify.json")
        _write(insight, "Body.\n")
        _write(sidecar, "{}")
        real_read = okf_v02_module.read_confined_text

        def refuse_sidecar(path: Path, root: Path, *, max_bytes: int) -> str | None:
            if path == sidecar:
                return None
            return real_read(path, root, max_bytes=max_bytes)

        monkeypatch.setattr(okf_v02_module, "read_confined_text", refuse_sidecar)

        with pytest.raises(ValueError, match="unreadable OKF verification sidecar"):
            export_okf_bundle(config, "ai")

    def test_export_rejects_oversized_source_without_replacing_prior_output(
        self, tmp_path: Path
    ) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        _write(topic_dir / "valid.md", "# Valid\n")
        oversized = topic_dir / "oversized.md"
        oversized.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
        prior_output = okf_bundle_output_dir(config.library_dir, "ai")
        marker = prior_output / "existing.txt"
        _write(marker, "preserve me")

        with pytest.raises(ValueError, match="unsafe or unreadable OKF source"):
            export_okf_bundle(config, "ai")

        assert marker.read_text(encoding="utf-8") == "preserve me"
        assert not (prior_output / "valid.md").exists()

    def test_later_source_read_failure_preserves_prior_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("ai")
        _write(topic_dir / "a.md", "# A\n")
        _write(topic_dir / "b.md", "# B\n")
        prior_output = okf_bundle_output_dir(config.library_dir, "ai")
        marker = prior_output / "existing.txt"
        _write(marker, "preserve me")
        real_read = okf_module.read_confined_text

        def fail_second_source(path: Path, root: Path, *, max_bytes: int) -> str | None:
            if path.name == "b.md":
                return None
            return real_read(path, root, max_bytes=max_bytes)

        monkeypatch.setattr(okf_module, "read_confined_text", fail_second_source)

        with pytest.raises(ValueError, match="unsafe or unreadable OKF source"):
            export_okf_bundle(config, "ai")

        assert marker.read_text(encoding="utf-8") == "preserve me"
        assert not list(prior_output.parent.glob(".okf-ai.staging-*"))

    def test_export_rejects_symlinked_topic_directory(self, tmp_path: Path) -> None:
        config = DistillConfig(distill_output_dir=tmp_path / "library")
        outside_topic = tmp_path / "outside-topic"
        _write(outside_topic / "secret.md", "private outside content")
        linked_topic = config.topic_dir("linked")
        linked_topic.parent.mkdir(parents=True)
        try:
            linked_topic.symlink_to(outside_topic, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlink creation unavailable: {exc}")

        with pytest.raises(ValueError, match="Source topic path is unsafe"):
            export_okf_bundle(config, "linked")


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
    def test_merge_supplemental_files_rejects_conflicting_content(self, tmp_path: Path) -> None:
        relative = Path("receipt.txt")
        first = okf_v02_module.SupplementalFile(tmp_path / "a.txt", relative, "first")
        second = okf_v02_module.SupplementalFile(tmp_path / "b.txt", relative, "second")
        collected: dict[Path, str] = {}

        okf_v02_module.merge_supplemental_files(collected, (first,))

        with pytest.raises(ValueError, match="Conflicting OKF supplemental file"):
            okf_v02_module.merge_supplemental_files(collected, (second,))

    @pytest.mark.parametrize(
        "receipt_name",
        ["../outside.txt", ".secret", "index.md", "log.md", "llms.txt", "folder/file.txt"],
    )
    def test_receipt_candidate_rejects_unsafe_or_reserved_names(
        self, tmp_path: Path, receipt_name: str
    ) -> None:
        source = tmp_path / "source.md"
        _write(source, "Source.\n")

        assert okf_v02_module.receipt_candidate(tmp_path, source, receipt_name) is None

    def test_okf_sources_tolerates_missing_receipt_mtime(self, tmp_path: Path, monkeypatch) -> None:
        source = tmp_path / "source.md"
        receipt = tmp_path / "receipt.txt"
        _write(source, "Source.\n")
        _write(receipt, "Receipt.\n")

        class BrokenTimestamp:
            @classmethod
            def fromtimestamp(cls, *_args, **_kwargs):
                raise OSError("mtime unavailable")

        monkeypatch.setattr(okf_v02_module, "datetime", BrokenTimestamp)

        sources, supplemental = okf_v02_module.collect_okf_sources(
            source_root=tmp_path,
            source_file=source,
            source_files=frozenset({source}),
            native_meta={"source_receipt": receipt.name},
            source_url="",
            title="Source",
            verification=None,
        )

        assert sources == [
            {
                "id": "source-receipt",
                "resource": "/receipt.txt",
                "title": "receipt.txt",
            }
        ]
        assert supplemental[0].content == "Receipt.\n"

    def test_okf_sources_refuses_unreadable_non_markdown_receipt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = tmp_path / "source.md"
        receipt = tmp_path / "receipt.txt"
        _write(source, "Source.\n")
        _write(receipt, "Receipt.\n")
        real_read = okf_v02_module.read_confined_text

        def refuse_receipt(path: Path, root: Path, *, max_bytes: int) -> str | None:
            if path == receipt:
                return None
            return real_read(path, root, max_bytes=max_bytes)

        monkeypatch.setattr(okf_v02_module, "read_confined_text", refuse_receipt)

        with pytest.raises(ValueError, match="unreadable OKF source receipt"):
            okf_v02_module.collect_okf_sources(
                source_root=tmp_path,
                source_file=source,
                source_files=frozenset({source}),
                native_meta={"source_receipt": receipt.name},
                source_url="",
                title="Source",
                verification=None,
            )

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

    def test_detect_staleness_none_when_topic_or_bundle_anchors_are_missing(
        self, tmp_path: Path
    ) -> None:
        library = tmp_path / "library"
        assert detect_okf_export_staleness(library, "ai") is None

        _write(library / "topics" / "ai" / ".hidden" / "ignored.md", "# hidden\n")
        (tmp_path / "output" / "okf-ai").mkdir(parents=True)
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
