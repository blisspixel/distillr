"""Tests for distill.corpus_analysis."""

from unittest.mock import patch

from distill.config import DistillConfig
from distill.library.paths import find_artifact, strip_frontmatter
from distill.llm.router import LLM_Response
from distill.pipeline.synthesis.corpus import synthesize_corpus


def _fake_llm_call(text: str = "body", model: str = "grok-4.3"):
    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(text=text, input_tokens=10, output_tokens=20, model=model)

    return _call


def test_synthesize_corpus_writes_output(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    topic_dir = config.topic_dir("mixed")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Topic", encoding="utf-8")
    (topic_dir / "paper_synthesis.md").write_text("# Paper", encoding="utf-8")

    site_dir = config.site_dir("mixed", "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("# Site", encoding="utf-8")

    with patch("distill.pipeline.synthesis.corpus.llm_call", _fake_llm_call("corpus synthesis")):
        result = synthesize_corpus("mixed", config)

    assert result == "corpus synthesis"
    output = find_artifact(topic_dir, "corpus_synthesis", identity="mixed")
    assert output.name == "mixed_Corpus_Synthesis.md"
    assert strip_frontmatter(output.read_text(encoding="utf-8")) == "corpus synthesis"
