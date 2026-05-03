"""Tests for the accordion method -- prompts, orchestrator, and assembly."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from distill.accordion import (
    _assemble_report,
    _clean_section_output,
    _count_sources,
    _extract_section_feedback,
    _gather_tagged_materials,
    _get_dossier_path,
    _get_research_path,
    _load_syntheses,
    _load_tagged_insights,
    _parse_qa_failures,
    _run_dossier_phase,
    _run_qa_phase,
    _scope_label,
    _write_sections,
    run_accordion_research,
)
from distill.artifacts import artifact_path, strip_frontmatter
from distill.llm.router import LLM_Response
from distill.prompts_accordion import (
    REPORT_SECTIONS,
    dossier_prompt,
    get_active_sections,
    section_prompt,
)

# ─── Prompt Tests ────────────────────────────────────────────────────


class TestReportSections:
    def test_section_count(self):
        assert len(REPORT_SECTIONS) == 10

    def test_all_sections_have_required_fields(self):
        for s in REPORT_SECTIONS:
            assert "id" in s
            assert "title" in s
            assert "position" in s
            assert "instructions" in s
            assert "dossier_focus" in s

    def test_positions_are_valid(self):
        valid = {"opening", "middle", "closing"}
        for s in REPORT_SECTIONS:
            assert s["position"] in valid, f"{s['id']} has invalid position: {s['position']}"

    def test_section_ids_are_unique(self):
        ids = [s["id"] for s in REPORT_SECTIONS]
        assert len(ids) == len(set(ids))

    def test_first_section_is_opening(self):
        assert REPORT_SECTIONS[0]["position"] == "opening"

    def test_last_section_is_closing(self):
        assert REPORT_SECTIONS[-1]["position"] == "closing"


class TestDossierPrompt:
    def test_includes_topic(self):
        result = dossier_prompt("ai", "test corpus")
        assert "ai" in result

    def test_includes_corpus(self):
        result = dossier_prompt("ai", "UNIQUE_CORPUS_CONTENT")
        assert "UNIQUE_CORPUS_CONTENT" in result

    def test_includes_focus_when_provided(self):
        result = dossier_prompt("ai", "corpus", focus="agentic systems")
        assert "agentic systems" in result

    def test_no_focus_when_none(self):
        result = dossier_prompt("ai", "corpus", focus=None)
        assert "SPECIFIC RESEARCH FOCUS" not in result

    def test_asks_for_raw_facts_not_report(self):
        result = dossier_prompt("ai", "corpus")
        assert "raw" in result.lower() or "RAW" in result
        assert "NOT want a polished report" in result

    def test_has_all_research_categories(self):
        result = dossier_prompt("ai", "corpus")
        assert "VALIDATED ANNOUNCEMENTS" in result
        assert "MARKET DATA" in result
        assert "COMPETITIVE POSITIONING" in result
        assert "ENTERPRISE ADOPTION" in result
        assert "PRICING AND ECONOMICS" in result
        assert "CORRECTIONS AND CONTRADICTIONS" in result
        assert "GAPS IN COVERAGE" in result
        assert "FORWARD-LOOKING SIGNALS" in result


class TestSectionPrompt:
    def test_includes_section_title(self):
        result = section_prompt(
            section=REPORT_SECTIONS[0],
            topic="ai",
            research_dossier="dossier content",
            previous_sections=[],
            section_index=0,
            total_sections=10,
        )
        assert REPORT_SECTIONS[0]["title"] in result

    def test_includes_dossier(self):
        result = section_prompt(
            section=REPORT_SECTIONS[0],
            topic="ai",
            research_dossier="UNIQUE_DOSSIER_TEXT",
            previous_sections=[],
            section_index=0,
            total_sections=10,
        )
        assert "UNIQUE_DOSSIER_TEXT" in result

    def test_first_section_says_first(self):
        result = section_prompt(
            section=REPORT_SECTIONS[0],
            topic="ai",
            research_dossier="dossier",
            previous_sections=[],
            section_index=0,
            total_sections=10,
        )
        assert "first section" in result.lower()

    def test_includes_previous_section_excerpts(self):
        prev = [
            {
                "title": "Exec Brief",
                "content": "The executive briefing content here",
                "word_count": 500,
            },
        ]
        result = section_prompt(
            section=REPORT_SECTIONS[1],
            topic="ai",
            research_dossier="dossier",
            previous_sections=prev,
            section_index=1,
            total_sections=10,
        )
        assert "Exec Brief" in result
        assert "500 words" in result

    def test_only_last_3_previous_sections(self):
        prev = [
            {
                "title": f"Section {i}",
                "content": f"Content for section {i}",
                "word_count": 100,
            }
            for i in range(5)
        ]
        result = section_prompt(
            section=REPORT_SECTIONS[5],
            topic="ai",
            research_dossier="dossier",
            previous_sections=prev,
            section_index=5,
            total_sections=10,
        )
        # Should include sections 2, 3, 4 (last 3) but not 0 or 1
        assert "Section 4" in result
        assert "Section 3" in result
        assert "Section 2" in result
        assert "Section 0" not in result
        assert "Section 1" not in result

    def test_single_channel_scope_swaps_consensus_section(self):
        active = get_active_sections(scope="channel", channel_count=1)

        assert len(active) == 10
        assert any(section["id"] == "creator_accuracy" for section in active)
        assert not any(section["id"] == "creator_consensus" for section in active)

    def test_multi_channel_scope_keeps_consensus_section(self):
        active = get_active_sections(scope="topic", channel_count=3)

        assert len(active) == 10
        assert any(section["id"] == "creator_consensus" for section in active)
        assert not any(section["id"] == "creator_accuracy" for section in active)

    def test_includes_tagged_material(self):
        result = section_prompt(
            section=REPORT_SECTIONS[2],
            topic="ai",
            research_dossier="dossier",
            previous_sections=[],
            section_index=2,
            total_sections=10,
            tagged_material="TAGGED_VENDOR_DATA",
        )
        assert "TAGGED_VENDOR_DATA" in result

    def test_position_guidance_applied(self):
        # Opening section
        result = section_prompt(
            section=REPORT_SECTIONS[0],
            topic="ai",
            research_dossier="dossier",
            previous_sections=[],
            section_index=0,
            total_sections=10,
        )
        assert "OPENING" in result

        # Closing section
        result = section_prompt(
            section=REPORT_SECTIONS[-1],
            topic="ai",
            research_dossier="dossier",
            previous_sections=[],
            section_index=9,
            total_sections=10,
        )
        assert "CLOSING" in result


# ─── Orchestrator Tests ──────────────────────────────────────────────


class TestAssembly:
    def test_assembles_sections(self, config):
        sections = [
            {
                "id": "exec",
                "title": "Executive Briefing",
                "content": "Brief content here.",
                "word_count": 3,
            },
            {
                "id": "landscape",
                "title": "Tech Landscape",
                "content": "Landscape content.",
                "word_count": 2,
            },
        ]
        result = _assemble_report("ai", config, "topic", None, sections)

        assert "Strategic Intelligence Report: AI" in result
        assert "Executive Briefing" in result
        assert "Tech Landscape" in result
        assert "Brief content here." in result
        assert "Table of Contents" in result

    def test_includes_word_counts_in_toc(self, config):
        sections = [
            {"id": "exec", "title": "Exec", "content": "x " * 500, "word_count": 500},
        ]
        result = _assemble_report("ai", config, "topic", None, sections)
        assert "500 words" in result

    def test_includes_metadata(self, config):
        sections = [
            {"id": "exec", "title": "Exec", "content": "content", "word_count": 1},
        ]
        result = _assemble_report("ai", config, "topic", None, sections)
        assert "Accordion method" in result


class TestScopeLabel:
    def test_channel_scope(self):
        assert "TestCh" in _scope_label("channel", "ai", "TestCh")

    def test_topic_scope(self):
        assert "ai" in _scope_label("topic", "ai", None)

    def test_all_scope(self):
        assert "Library" in _scope_label("all", "ai", None)


class TestDossierPath:
    def test_topic_path(self, config):
        path = _get_dossier_path("ai", config, "topic", None)
        assert path.name == "dossier.md"
        assert "ai" in str(path)

    def test_channel_path(self, config):
        path = _get_dossier_path("ai", config, "channel", "TestCh")
        assert path.name == "dossier.md"
        assert "TestCh" in str(path)

    def test_all_path(self, config):
        path = _get_dossier_path("all", config, "all", None)
        assert path.name == "dossier.md"


class TestResearchPath:
    def test_topic_path(self, config):
        path = _get_research_path("ai", config, "topic", None)
        assert path.name == "ai_Research.md"
        assert "ai" in str(path)

    def test_channel_path(self, config):
        path = _get_research_path("ai", config, "channel", "TestCh")
        assert path.name == "ai_TestCh_Research.md"
        assert "TestCh" in str(path)

    def test_all_path(self, config):
        path = _get_research_path("all", config, "all", None)
        assert path.name == "library_Research.md"


class TestCountSources:
    def test_counts_videos(self, populated_channel):
        config, _lib = populated_channel
        vids, channels = _count_sources("ai", config, "topic", None)
        assert vids == 3
        assert channels == 1


class TestTaggedMaterials:
    def test_loads_syntheses(self, populated_channel):
        config, _lib = populated_channel
        tagged = _gather_tagged_materials("ai", config, "topic", None)
        assert "creator_consensus" in tagged
        assert "Channel Synthesis" in tagged["creator_consensus"]


class TestWriteSections:
    @patch("distill.accordion.time.sleep")
    @patch("distill.accordion.llm_call")
    def test_writes_all_sections(self, mock_call, mock_sleep, config):
        mock_call.return_value = LLM_Response(
            text="Section content with enough words to count.",
            input_tokens=10, output_tokens=20, model="grok-4.3",
        )

        result = _write_sections(
            topic="ai",
            config=config,
            dossier="test dossier",
            scope="topic",
            channel_name=None,
            tagged_materials={},
        )
        assert len(result) == 10
        assert all(s["word_count"] > 0 for s in result)

    @patch("distill.accordion.time.sleep")
    @patch("distill.accordion.llm_call")
    def test_filters_sections(self, mock_call, mock_sleep, config):
        mock_call.return_value = LLM_Response(
            text="Filtered section content.",
            input_tokens=10, output_tokens=20, model="grok-4.3",
        )

        result = _write_sections(
            topic="ai",
            config=config,
            dossier="test dossier",
            scope="topic",
            channel_name=None,
            tagged_materials={},
            filter_sections=["executive_briefing", "strategic_synthesis"],
        )
        assert len(result) == 2
        assert result[0]["id"] == "executive_briefing"
        assert result[1]["id"] == "strategic_synthesis"

    @patch("distill.accordion.time.sleep")
    @patch("distill.accordion.llm_call")
    def test_stops_after_3_consecutive_failures(self, mock_call, mock_sleep, config):
        mock_call.return_value = LLM_Response(
            text="", input_tokens=0, output_tokens=0, model="grok-4.3",
        )

        result = _write_sections(
            topic="ai",
            config=config,
            dossier="test dossier",
            scope="topic",
            channel_name=None,
            tagged_materials={},
        )
        assert len(result) == 0

    @patch("distill.accordion.time.sleep")
    @patch("distill.accordion.llm_call")
    def test_uses_active_sections_override(self, mock_call, mock_sleep, config):
        mock_call.return_value = LLM_Response(
            text="Override content.",
            input_tokens=10, output_tokens=20, model="grok-4.3",
        )
        active_sections = [REPORT_SECTIONS[0], REPORT_SECTIONS[1]]

        result = _write_sections(
            topic="ai",
            config=config,
            dossier="test dossier",
            scope="topic",
            channel_name=None,
            tagged_materials={},
            active_sections=active_sections,
        )

        assert [section["id"] for section in result] == [
            REPORT_SECTIONS[0]["id"],
            REPORT_SECTIONS[1]["id"],
        ]


class TestQaHelpers:
    def test_parse_qa_failures_extracts_failed_sections(self):
        qa = """### Executive Briefing
**Score**: FAIL
### OVERALL
**Score**: PASS
### Strategic Synthesis
**Score**: FAIL
"""

        assert _parse_qa_failures(qa) == ["Executive Briefing", "Strategic Synthesis"]

    def test_extract_section_feedback_groups_by_heading(self):
        qa = """### Executive Briefing
Needs more evidence
### Strategic Synthesis
Needs less repetition
"""

        feedback = _extract_section_feedback(qa)

        assert "Needs more evidence" in feedback["Executive Briefing"]
        assert "Needs less repetition" in feedback["Strategic Synthesis"]

    def test_clean_section_output_strips_word_counts_and_citations(self):
        content = "Body text [cite: 1, 2] (Word count: 1,234)"

        assert _clean_section_output(content) == "Body text"


class TestTaggedHelpers:
    def test_load_syntheses_includes_topic_synthesis(self, populated_channel):
        config, _lib = populated_channel
        (config.topic_dir("ai") / "topic_synthesis.md").write_text(
            "# Topic Synthesis", encoding="utf-8"
        )

        loaded = _load_syntheses("ai", config, "topic", None)

        assert "Channel Synthesis" in loaded
        assert "Topic Synthesis: ai" in loaded

    def test_load_tagged_insights_filters_by_keyword(self, populated_channel):
        config, _lib = populated_channel

        loaded = _load_tagged_insights(
            "ai", config, "topic", None, keywords=["Insight 1"], max_chars=10000
        )

        assert "Test Video 1" in loaded
        assert "Test Video 0" not in loaded

    def test_load_syntheses_across_all_topics(self, config):
        for topic, channel in [("ai", "Alpha"), ("security", "Beta")]:
            ch_dir = config.channel_dir(topic, channel)
            ch_dir.mkdir(parents=True, exist_ok=True)
            (ch_dir / "synthesis.md").write_text(f"# {channel} synthesis", encoding="utf-8")

        loaded = _load_syntheses("ai", config, "all", None)

        assert "Alpha Channel Synthesis" in loaded
        assert "Beta Channel Synthesis" in loaded

    def test_load_tagged_insights_respects_max_chars(self, config):
        config.channel_dir("ai", "TestChannel").mkdir(parents=True, exist_ok=True)
        for idx in range(2):
            vid_dir = config.video_dir("ai", "TestChannel", f"vid{idx}")
            vid_dir.mkdir(parents=True, exist_ok=True)
            (vid_dir / "metadata.json").write_text(f'{{"title":"Video {idx}"}}', encoding="utf-8")
            (vid_dir / "insights.md").write_text(
                "Microsoft enterprise deployment notes " * 3,
                encoding="utf-8",
            )

        loaded = _load_tagged_insights(
            "ai",
            config,
            "all",
            None,
            keywords=["Microsoft"],
            max_chars=150,
        )

        assert "Video 0" in loaded
        assert "Video 1" not in loaded


class TestQaPhase:
    @patch("distill.accordion.llm_call")
    def test_run_qa_phase_rewrites_failed_section(self, mock_call, config):
        written_sections = [
            {
                "id": "executive_briefing",
                "title": "Executive Briefing",
                "content": "old content",
                "word_count": 2,
            },
            {
                "id": "strategic_synthesis",
                "title": "Strategic Synthesis",
                "content": "keep content",
                "word_count": 2,
            },
        ]
        mock_call.side_effect = [
            LLM_Response(
                text="### Executive Briefing\n**Score**: FAIL\nFix this.\n### Strategic Synthesis\n**Score**: PASS",
                input_tokens=10, output_tokens=20, model="grok-4.3",
            ),
            LLM_Response(
                text="rewritten content [cite: 1]",
                input_tokens=10, output_tokens=20, model="grok-4.3",
            ),
        ]

        updated, rewrote = _run_qa_phase("ai", config, "dossier", "report", written_sections)

        assert rewrote == 1
        assert updated[0]["content"] == "rewritten content"
        assert updated[1]["content"] == "keep content"

    @patch("distill.accordion.llm_call")
    def test_run_qa_phase_skips_when_review_fails(self, mock_call, config):
        written_sections = [
            {
                "id": "executive_briefing",
                "title": "Executive Briefing",
                "content": "old content",
                "word_count": 2,
            },
        ]
        mock_call.side_effect = Exception("boom")

        updated, rewrote = _run_qa_phase("ai", config, "dossier", "report", written_sections)

        assert rewrote == 0
        assert updated == written_sections

    @patch("distill.accordion.llm_call")
    def test_run_qa_phase_with_no_failures(self, mock_call, config):
        written_sections = [
            {
                "id": "executive_briefing",
                "title": "Executive Briefing",
                "content": "old content",
                "word_count": 2,
            },
        ]
        mock_call.return_value = LLM_Response(
            text="### Executive Briefing\n**Score**: PASS\nLooks good.",
            input_tokens=10, output_tokens=20, model="grok-4.3",
        )

        updated, rewrote = _run_qa_phase("ai", config, "dossier", "report", written_sections)

        assert rewrote == 0
        assert updated == written_sections

    @patch("distill.accordion.llm_call")
    def test_run_qa_phase_keeps_original_when_rewrite_fails(self, mock_call, config):
        written_sections = [
            {
                "id": "executive_briefing",
                "title": "Executive Briefing",
                "content": "old content",
                "word_count": 2,
            },
        ]
        mock_call.side_effect = [
            LLM_Response(
                text="### Executive Briefing\n**Score**: FAIL",
                input_tokens=10, output_tokens=20, model="grok-4.3",
            ),
            Exception("boom"),
        ]

        updated, rewrote = _run_qa_phase("ai", config, "dossier", "report", written_sections)

        assert rewrote == 0
        assert updated[0]["content"] == "old content"

    @patch("distill.accordion.llm_call")
    def test_run_qa_phase_ignores_unknown_section_ids(self, mock_call, config):
        written_sections = [
            {
                "id": "missing_id",
                "title": "Unknown Section",
                "content": "old content",
                "word_count": 2,
            },
        ]
        mock_call.return_value = LLM_Response(
            text="### Unknown Section\n**Score**: FAIL\nNeeds work.",
            input_tokens=10, output_tokens=20, model="grok-4.3",
        )

        updated, rewrote = _run_qa_phase("ai", config, "dossier", "report", written_sections)

        assert rewrote == 0
        assert updated == written_sections


class TestDossierPhase:
    @patch("distill.accordion.time.sleep", lambda seconds: None)
    def test_run_dossier_phase_returns_none_when_no_files(self, config, monkeypatch):
        monkeypatch.setattr(
            "distill.accordion.create_research_store",
            lambda *args, **kwargs: ("store-1", 0),
        )
        deleted = []
        monkeypatch.setattr(
            "distill.accordion.delete_store", lambda client, name: deleted.append(name)
        )

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.interactions = SimpleNamespace()

        monkeypatch.setattr("distill.accordion.genai.Client", FakeClient)

        result = _run_dossier_phase("ai", config, "topic", None, None, False)

        assert result is None
        assert deleted == ["store-1"]

    @patch("distill.accordion.time.sleep", lambda seconds: None)
    def test_run_dossier_phase_returns_output_on_completion(self, config, monkeypatch):
        deleted = []
        monkeypatch.setattr(
            "distill.accordion.create_research_store",
            lambda *args, **kwargs: ("store-1", 2),
        )
        monkeypatch.setattr(
            "distill.accordion.delete_store", lambda client, name: deleted.append(name)
        )

        class FakeInteractions:
            def create(self, **kwargs):
                return SimpleNamespace(id="job-1")

            def get(self, interaction_id):
                return SimpleNamespace(
                    status="completed", outputs=[SimpleNamespace(text="dossier body")]
                )

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.interactions = FakeInteractions()

        monkeypatch.setattr("distill.accordion.genai.Client", FakeClient)

        result = _run_dossier_phase("ai", config, "topic", None, None, False)

        assert result == "dossier body"
        assert deleted == ["store-1"]

    @patch("distill.accordion.time.sleep", lambda seconds: None)
    def test_run_dossier_phase_returns_none_on_failed_status(self, config, monkeypatch):
        deleted = []
        monkeypatch.setattr(
            "distill.accordion.create_research_store",
            lambda *args, **kwargs: ("store-1", 2),
        )
        monkeypatch.setattr(
            "distill.accordion.delete_store", lambda client, name: deleted.append(name)
        )

        class FakeInteractions:
            def create(self, **kwargs):
                return SimpleNamespace(id="job-1")

            def get(self, interaction_id):
                return SimpleNamespace(status="failed", error="bad request")

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.interactions = FakeInteractions()

        monkeypatch.setattr("distill.accordion.genai.Client", FakeClient)

        result = _run_dossier_phase("ai", config, "topic", None, None, False)

        assert result is None
        assert deleted == ["store-1", "store-1"]

    @patch("distill.accordion.time.sleep", lambda seconds: None)
    def test_run_dossier_phase_returns_none_when_output_empty(self, config, monkeypatch):
        deleted = []
        monkeypatch.setattr(
            "distill.accordion.create_research_store",
            lambda *args, **kwargs: ("store-1", 2),
        )
        monkeypatch.setattr(
            "distill.accordion.delete_store", lambda client, name: deleted.append(name)
        )

        class FakeInteractions:
            def create(self, **kwargs):
                return SimpleNamespace(id="job-1")

            def get(self, interaction_id):
                return SimpleNamespace(status="completed", outputs=[])

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.interactions = FakeInteractions()

        monkeypatch.setattr("distill.accordion.genai.Client", FakeClient)

        result = _run_dossier_phase("ai", config, "topic", None, None, False)

        assert result is None
        assert deleted == ["store-1", "store-1"]

    @patch("distill.accordion.time.sleep", lambda seconds: None)
    def test_run_dossier_phase_records_tracker_usage(self, config, monkeypatch):
        tracker = MagicMock()
        monkeypatch.setattr(
            "distill.accordion.create_research_store",
            lambda *args, **kwargs: ("store-1", 2),
        )
        monkeypatch.setattr("distill.accordion.delete_store", lambda *args, **kwargs: None)

        class FakeInteractions:
            def create(self, **kwargs):
                return SimpleNamespace(id="job-1")

            def get(self, interaction_id):
                return SimpleNamespace(
                    status="completed", outputs=[SimpleNamespace(text="dossier body")]
                )

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.interactions = FakeInteractions()

        monkeypatch.setattr("distill.accordion.genai.Client", FakeClient)

        result = _run_dossier_phase("ai", config, "topic", None, None, False, tracker=tracker)

        assert result == "dossier body"
        tracker.record_gemini_query.assert_called_once_with()


class TestAccordionRun:
    def test_run_accordion_research_returns_none_when_dossier_fails(self, config, monkeypatch):
        monkeypatch.setattr("distill.accordion._run_dossier_phase", lambda *args, **kwargs: None)

        result = run_accordion_research("ai", config)

        assert result is None

    def test_run_accordion_research_dossier_only(self, config, monkeypatch):
        monkeypatch.setattr(
            "distill.accordion._run_dossier_phase",
            lambda *args, **kwargs: "dossier body",
        )
        monkeypatch.setattr("distill.accordion._count_sources", lambda *args, **kwargs: (3, 2))

        result = run_accordion_research("ai", config, dossier_only=True)

        assert result == "dossier body"
        research_path = artifact_path(config.topic_dir("ai"), "research", identity="ai")
        assert strip_frontmatter(research_path.read_text(encoding="utf-8")) == "dossier body"

    def test_run_accordion_research_returns_none_when_sections_empty(self, config, monkeypatch):
        monkeypatch.setattr(
            "distill.accordion._run_dossier_phase",
            lambda *args, **kwargs: "dossier body",
        )
        monkeypatch.setattr("distill.accordion._count_sources", lambda *args, **kwargs: (3, 2))
        monkeypatch.setattr(
            "distill.accordion._gather_tagged_materials", lambda *args, **kwargs: {}
        )
        monkeypatch.setattr("distill.accordion._write_sections", lambda *args, **kwargs: [])

        result = run_accordion_research("ai", config)

        assert result is None

    def test_run_accordion_research_full_flow_without_qa(self, config, monkeypatch):
        monkeypatch.setattr(
            "distill.accordion._run_dossier_phase",
            lambda *args, **kwargs: "dossier body",
        )
        monkeypatch.setattr("distill.accordion._count_sources", lambda *args, **kwargs: (3, 2))
        monkeypatch.setattr(
            "distill.accordion._gather_tagged_materials", lambda *args, **kwargs: {}
        )
        monkeypatch.setattr(
            "distill.accordion._write_sections",
            lambda *args, **kwargs: [
                {
                    "id": "executive_briefing",
                    "title": "Executive Briefing",
                    "content": "section body",
                    "word_count": 2,
                },
            ],
        )

        result = run_accordion_research("ai", config, skip_qa=True)

        assert "section body" in result
        assert artifact_path(config.topic_dir("ai"), "report", identity="ai").exists()

    def test_run_accordion_research_reassembles_after_qa_rewrite(self, config, monkeypatch):
        monkeypatch.setattr(
            "distill.accordion._run_dossier_phase",
            lambda *args, **kwargs: "dossier body",
        )
        monkeypatch.setattr("distill.accordion._count_sources", lambda *args, **kwargs: (3, 2))
        monkeypatch.setattr(
            "distill.accordion._gather_tagged_materials", lambda *args, **kwargs: {}
        )
        monkeypatch.setattr(
            "distill.accordion._write_sections",
            lambda *args, **kwargs: [
                {
                    "id": "executive_briefing",
                    "title": "Executive Briefing",
                    "content": "original",
                    "word_count": 1,
                },
            ],
        )
        monkeypatch.setattr(
            "distill.accordion._run_qa_phase",
            lambda *args, **kwargs: (
                [
                    {
                        "id": "executive_briefing",
                        "title": "Executive Briefing",
                        "content": "rewritten",
                        "word_count": 1,
                    },
                ],
                1,
            ),
        )

        result = run_accordion_research("ai", config)

        assert "rewritten" in result
