from distill.artifacts import find_artifact, strip_frontmatter
from distill.config import DistillConfig
from distill.corpus_analysis import synthesize_corpus


def test_synthesize_corpus_writes_output(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    topic_dir = config.topic_dir("mixed")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Topic", encoding="utf-8")
    (topic_dir / "paper_synthesis.md").write_text("# Paper", encoding="utf-8")

    site_dir = config.site_dir("mixed", "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("# Site", encoding="utf-8")

    monkeypatch.setattr("distill.corpus_analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.corpus_analysis._call_grok",
        lambda client, prompt, model, tracker=None, call_type="": "corpus synthesis",
    )

    result = synthesize_corpus("mixed", config)

    assert result == "corpus synthesis"
    output = find_artifact(topic_dir, "corpus_synthesis", identity="mixed")
    assert output.name == "mixed_Corpus_Synthesis.md"
    assert strip_frontmatter(output.read_text(encoding="utf-8")) == "corpus synthesis"
