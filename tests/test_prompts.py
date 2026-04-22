"""Tests for distill.prompts — ensure prompt generation doesn't crash with edge cases."""

from distill.prompts import (
    channel_context_prompt,
    channel_synthesis_prompt,
    corpus_synthesis_prompt,
    deep_research_prompt,
    pass1_extraction_prompt,
    pass2_synthesis_prompt,
    topic_synthesis_prompt,
)


class TestPass1Prompt:
    def test_basic(self):
        result = pass1_extraction_prompt("Title", "20250101", "Channel", "Some transcript")
        assert "Title" in result
        assert "Channel" in result
        assert "Some transcript" in result

    def test_empty_transcript(self):
        result = pass1_extraction_prompt("Title", "20250101", "Channel", "")
        assert isinstance(result, str)
        assert "Title" in result

    def test_unicode_in_title(self):
        result = pass1_extraction_prompt("AI & ML: What's Next?", "20250101", "Ch", "text")
        assert "AI & ML" in result

    def test_quotes_in_title(self):
        result = pass1_extraction_prompt('He said "hello"', "20250101", "Ch", "text")
        assert '"hello"' in result

    def test_very_long_transcript(self):
        transcript = "word " * 100000
        result = pass1_extraction_prompt("T", "20250101", "Ch", transcript)
        assert isinstance(result, str)


class TestPass2Prompt:
    def test_basic(self):
        result = pass2_synthesis_prompt("Title", "20250101", "Channel", "pass1 output")
        assert "Title" in result
        assert "pass1 output" in result

    def test_empty_pass1(self):
        result = pass2_synthesis_prompt("Title", "20250101", "Channel", "")
        assert isinstance(result, str)


class TestChannelContextPrompt:
    def test_basic(self):
        titles = ["Video 1", "Video 2", "Video 3"]
        result = channel_context_prompt("TestChannel", titles)
        assert "TestChannel" in result
        assert "Video 1" in result

    def test_empty_titles(self):
        result = channel_context_prompt("Ch", [])
        assert isinstance(result, str)
        assert "Ch" in result

    def test_many_titles_truncated(self):
        titles = [f"Video {i}" for i in range(50)]
        result = channel_context_prompt("Ch", titles)
        # Should only include first 20
        assert "Video 0" in result
        assert "Video 19" in result
        assert "Video 20" not in result


class TestChannelSynthesisPrompt:
    def test_basic(self):
        result = channel_synthesis_prompt("Ch", "context", "insights")
        assert "Ch" in result
        assert "context" in result
        assert "insights" in result

    def test_empty_context(self):
        result = channel_synthesis_prompt("Ch", "", "insights")
        assert isinstance(result, str)

    def test_empty_insights(self):
        result = channel_synthesis_prompt("Ch", "ctx", "")
        assert isinstance(result, str)


class TestTopicSynthesisPrompt:
    def test_basic(self):
        channel_syntheses = {"ChA": "Synthesis A", "ChB": "Synthesis B"}
        result = topic_synthesis_prompt("ai", channel_syntheses)
        assert "ai" in result
        assert "ChA" in result
        assert "Synthesis A" in result

    def test_empty_syntheses(self):
        result = topic_synthesis_prompt("ai", {})
        assert isinstance(result, str)

    def test_single_channel(self):
        result = topic_synthesis_prompt("ai", {"ChA": "content"})
        assert "ChA" in result

    def test_source_origin_attribution_language(self):
        result = topic_synthesis_prompt("ai", {"ChA": "content"})
        assert "widely repeated" in result
        assert "originating claim" in result


class TestCorpusSynthesisPrompt:
    def test_source_origin_attribution_language(self):
        result = corpus_synthesis_prompt("ai", {"YouTube": "creator view", "Paper": "paper view"})
        assert "widely repeated" in result
        assert "independent confirmation" in result


class TestDeepResearchPrompt:
    def test_basic(self):
        result = deep_research_prompt("ai", "corpus text")
        assert "ai" in result
        assert "corpus text" in result
        assert "TRACE ORIGINS" in result
        assert "independently corroborated" in result

    def test_with_focus(self):
        result = deep_research_prompt("ai", "corpus", focus="GPU pricing")
        assert "GPU pricing" in result

    def test_without_focus(self):
        result = deep_research_prompt("ai", "corpus", focus=None)
        assert "SPECIFIC RESEARCH FOCUS" not in result

    def test_empty_corpus(self):
        result = deep_research_prompt("ai", "")
        assert isinstance(result, str)
