"""MCP tool tests for find_concepts, read_concept, concept_history/diff."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.config import DistillConfig
from distill.mcp.tools.concepts import (
    concept_diff,
    concept_history,
    find_concepts,
    read_concept,
)


@pytest.fixture
def mock_config(tmp_path: Path) -> DistillConfig:
    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def _seed_topic(config: DistillConfig, topic: str = "tkg") -> Path:
    topic_dir = config.topic_dir(topic)
    topic_dir.mkdir(parents=True)
    (topic_dir / "concepts.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {
                    "name": "Rotational Embeddings",
                    "slug": "rotational_embedding",
                    "kind": "technique",
                    "topic": "tkg",
                    "source_count": 5,
                    "helpful_count": 5,
                    "harmful_count": 0,
                    "contested": False,
                },
                {
                    "name": "Disputed Method",
                    "slug": "disputed_method",
                    "kind": "technique",
                    "topic": "tkg",
                    "source_count": 4,
                    "helpful_count": 2,
                    "harmful_count": 2,
                    "contested": True,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (topic_dir / "entities.jsonl").write_text(
        json.dumps(
            {
                "name": "OpenAI",
                "slug": "openai",
                "kind": "vendor",
                "topic": "tkg",
                "source_count": 3,
                "helpful_count": 3,
                "harmful_count": 0,
                "contested": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Also write actual concept .md files for read_concept
    (topic_dir / "concepts").mkdir()
    (topic_dir / "concepts" / "rotational_embedding.md").write_text(
        "---\ntype: concept\n---\n\n# Rotational Embeddings\n\nbody\n", encoding="utf-8"
    )
    (topic_dir / "concepts" / "disputed_method.md").write_text(
        "---\ntype: concept\n---\n\n# Disputed\nbody\n", encoding="utf-8"
    )
    (topic_dir / "entities").mkdir()
    (topic_dir / "entities" / "openai.md").write_text(
        "---\ntype: entity\n---\n\n# OpenAI\nbody\n", encoding="utf-8"
    )
    return topic_dir


class TestFindConcepts:
    def test_missing_topic_returns_error(self, mock_config: DistillConfig) -> None:
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("ghost"))
        assert result["status"] == "error"

    def test_returns_all_when_no_filters(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg"))
        assert result["count"] == 3
        # Sorted by source_count desc
        assert result["results"][0]["name"] == "Rotational Embeddings"

    def test_contested_only_filter(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", contested_only=True))
        assert result["count"] == 1
        assert result["results"][0]["name"] == "Disputed Method"

    def test_query_substring_match(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", query="rotation"))
        assert result["count"] == 1
        assert result["results"][0]["name"] == "Rotational Embeddings"

    def test_kind_filter(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", kind="vendor"))
        assert result["count"] == 1
        assert result["results"][0]["name"] == "OpenAI"

    def test_path_uses_entities_dir_for_entities(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", kind="vendor"))
        assert "entities/openai.md" in result["results"][0]["path"]

    def test_limit_applied(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", limit=1))
        assert result["count"] == 1


class TestReadConcept:
    def test_reads_concept_strips_frontmatter(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("topics/tkg/concepts/rotational_embedding.md"))
        assert "type: concept" not in result["content"]  # frontmatter stripped
        assert "Rotational Embeddings" in result["content"]

    def test_absolute_path_rejected(self, mock_config: DistillConfig) -> None:
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("/etc/passwd"))
        assert result["status"] == "error"

    def test_non_concept_path_rejected(self, mock_config: DistillConfig) -> None:
        topic_dir = _seed_topic(mock_config)
        rogue = topic_dir / "rogue.md"
        rogue.write_text("body", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("topics/tkg/rogue.md"))
        assert result["status"] == "error"
        assert "concept" in result["error"].lower()

    def test_traversal_bypass_with_fake_concepts_segment_rejected(
        self, mock_config: DistillConfig
    ) -> None:
        """concepts/../secret.md must not pass the concept/entity guard.

        Regression: the earlier substring check on the raw path let any
        input containing '/concepts/' through. The fix checks the
        resolved path's directory parts, which is order-independent and
        doesn't care about path strings.
        """
        topic_dir = _seed_topic(mock_config)
        secret = topic_dir / "secret.md"
        secret.write_text("private corpus data", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            # The raw string contains '/concepts/' but the resolved path
            # is topics/tkg/secret.md -- outside concepts/.
            result = json.loads(read_concept("topics/tkg/concepts/../secret.md"))
        assert result["status"] == "error"
        assert "private corpus data" not in result.get("content", "")

    def test_traversal_to_dotdistill_rejected(self, mock_config: DistillConfig) -> None:
        """Traversal into .distill (task files / prompts) must not pass."""
        _seed_topic(mock_config)
        ops_dir = mock_config.library_dir / ".distill" / "tasks"
        ops_dir.mkdir(parents=True)
        (ops_dir / "task.md").write_text("private prompt payload", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("topics/tkg/concepts/../../../.distill/tasks/task.md"))
        assert result["status"] == "error"
        assert "private prompt payload" not in result.get("content", "")

    def test_missing_file_error(self, mock_config: DistillConfig) -> None:
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("topics/ghost/concepts/x.md"))
        assert result["status"] == "error"

    def test_library_under_concepts_ancestor_does_not_bypass_guard(self, tmp_path: Path) -> None:
        """library_dir under an absolute ancestor named 'concepts' must not
        grant read access to non-playbook library files.

        Regression: the prior guard checked ``full_path.parts`` (absolute
        components). When ``DISTILL_OUTPUT_DIR`` lives under a directory
        named ``concepts`` or ``entities`` -- a realistic config-dependent
        case -- every library file's absolute parts contain "concepts" and
        pass the guard, disclosing non-playbook files (synthesis output,
        ``.distill`` task artifacts, etc.) to the MCP caller.
        """
        ancestor = tmp_path / "concepts" / "library"
        ancestor.mkdir(parents=True)
        config = DistillConfig(xai_api_key="t", distill_output_dir=ancestor)
        _seed_topic(config)
        topic_dir = config.topic_dir("tkg")
        (topic_dir / "secret.md").write_text("private corpus data", encoding="utf-8")
        ops = config.library_dir / ".distill" / "tasks"
        ops.mkdir(parents=True)
        (ops / "task.md").write_text("private prompt payload", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=config):
            for path, sentinel in [
                ("topics/tkg/secret.md", "private corpus data"),
                (".distill/tasks/task.md", "private prompt payload"),
            ]:
                result = json.loads(read_concept(path))
                assert result["status"] == "error", f"{path} should be rejected"
                assert sentinel not in result.get("content", "")
            # Sanity: legitimate playbook reads still work under the same config
            ok = json.loads(read_concept("topics/tkg/concepts/rotational_embedding.md"))
            assert "Rotational Embeddings" in ok["content"]

    def test_library_under_entities_ancestor_does_not_bypass_guard(self, tmp_path: Path) -> None:
        """Same bypass class for an ``entities`` ancestor."""
        ancestor = tmp_path / "entities" / "library"
        ancestor.mkdir(parents=True)
        config = DistillConfig(xai_api_key="t", distill_output_dir=ancestor)
        _seed_topic(config)
        topic_dir = config.topic_dir("tkg")
        (topic_dir / "secret.md").write_text("private corpus data", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=config):
            result = json.loads(read_concept("topics/tkg/secret.md"))
        assert result["status"] == "error"
        assert "private corpus data" not in result.get("content", "")

    def test_history_snapshot_path_rejected(self, mock_config: DistillConfig) -> None:
        """``.history/<slug>/<ts>.md`` is not a live playbook note.

        Dedicated MCP tools (``concept_history`` / ``concept_diff``, 0.8.2)
        read snapshots; ``read_concept``'s contract is the live note only.
        """
        topic_dir = _seed_topic(mock_config)
        hist = topic_dir / ".history" / "rotational_embedding" / "2026-05-15T00-00-00.md"
        hist.parent.mkdir(parents=True)
        hist.write_text("snapshot body", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(
                read_concept("topics/tkg/.history/rotational_embedding/2026-05-15T00-00-00.md")
            )
        assert result["status"] == "error"
        assert "snapshot body" not in result.get("content", "")

    def test_non_markdown_in_concepts_dir_rejected(self, mock_config: DistillConfig) -> None:
        """Sidecar/non-markdown files in concepts/ are not playbook notes."""
        topic_dir = _seed_topic(mock_config)
        sidecar = topic_dir / "concepts" / "stash.txt"
        sidecar.write_text("not a note", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("topics/tkg/concepts/stash.txt"))
        assert result["status"] == "error"
        assert "not a note" not in result.get("content", "")

    def test_top_level_md_outside_topics_rejected(self, mock_config: DistillConfig) -> None:
        """A markdown file at the library root must not pass the shape check."""
        rogue = mock_config.library_dir / "README.md"
        rogue.write_text("library root readme", encoding="utf-8")
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(read_concept("README.md"))
        assert result["status"] == "error"
        assert "library root readme" not in result.get("content", "")


class TestContestedRetrieval:
    """Contested-only retrieval lives on find_concepts; the duplicate
    list_contested tool was removed in 0.9.30 (every always-loaded tool schema
    costs the consuming agent context)."""

    def test_contested_only_filter(self, mock_config: DistillConfig) -> None:
        _seed_topic(mock_config)
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(find_concepts("tkg", contested_only=True))
        assert result["count"] == 1
        assert result["results"][0]["name"] == "Disputed Method"
        assert result["results"][0]["contested"] is True

    def test_list_contested_tool_is_gone(self) -> None:
        import distill.mcp.tools.concepts as mod

        assert not hasattr(mod, "list_contested")


def _build_history(topic_dir: Path) -> None:
    """Two writes -> one history snapshot, via the real write path."""
    from distill.concepts.exports import write_exports
    from distill.concepts.notes import write_playbook
    from distill.concepts.records import (
        ConceptKind,
        EvidenceInterval,
        MergedConcept,
        Polarity,
        SourceEvidence,
    )

    def _c(sources: list[tuple[str, Polarity]], helpful: tuple[int, int], last_seen: str):
        srcs = tuple(
            SourceEvidence(source_id=s, artifact_path=f"papers/{s}/{s}_Insights.md", polarity=p)
            for s, p in sources
        )
        return MergedConcept(
            name="Rotational Embedding",
            normalized_name="rotational embedding",
            kind=ConceptKind.TECHNIQUE,
            topic="tkg",
            sources=srcs,
            helpful_evidence=EvidenceInterval(*helpful),
            harmful_evidence=EvidenceInterval(0, 0),
            first_seen="2026-05-01T00:00:00Z",
            last_seen=last_seen,
        )

    topic_dir.mkdir(parents=True, exist_ok=True)
    v1 = _c([("A", Polarity.HELPFUL), ("B", Polarity.HELPFUL)], (2, 2), "2026-05-28T07:00:00Z")
    write_playbook(topic_dir, v1, now_iso="2026-05-28T07:00:00Z")
    write_exports(topic_dir, [v1])
    v2 = _c(
        [("A", Polarity.HELPFUL), ("B", Polarity.HELPFUL), ("C", Polarity.HELPFUL)],
        (3, 3),
        "2026-05-29T08:10:31Z",
    )
    write_playbook(topic_dir, v2, now_iso="2026-05-29T08:10:31Z")
    write_exports(topic_dir, [v2])


class TestConceptHistory:
    def test_missing_topic_errors(self, mock_config: DistillConfig) -> None:
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(concept_history("ghost", "x"))
        assert result["status"] == "error"

    def test_lists_history_steps(self, mock_config: DistillConfig) -> None:
        _build_history(mock_config.topic_dir("tkg"))
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(concept_history("tkg", "rotational_embedding"))
        assert result["snapshot_count"] == 1
        assert result["has_live_note"] is True
        assert result["history"][0]["timestamp"] == "2026-05-29T08:10:31Z"
        assert "+1 source" in result["history"][0]["change"]


class TestConceptDiff:
    def test_snapshot_vs_current(self, mock_config: DistillConfig) -> None:
        _build_history(mock_config.topic_dir("tkg"))
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(concept_diff("tkg", "rotational_embedding"))
        assert result["sources_added"] == ["C"]
        assert result["old"] == "2026-05-29T08:10:31Z"
        assert result["new"] == "current"

    def test_unknown_timestamp_errors(self, mock_config: DistillConfig) -> None:
        _build_history(mock_config.topic_dir("tkg"))
        with patch("distill.mcp.server._config", return_value=mock_config):
            result = json.loads(
                concept_diff("tkg", "rotational_embedding", "1999-01-01", "2000-01-01")
            )
        assert result["status"] == "error"
