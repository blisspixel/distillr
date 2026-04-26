from distill.config import DistillConfig
from distill.costs import CostTracker
from distill.synthesize import compose_synthesis_prompt, run_synthesis


def test_compose_synthesis_prompt_includes_context_and_sources():
    prompt = compose_synthesis_prompt("Focus on mechanisms", [("paper-1", "details here")])

    assert "Focus on mechanisms" in prompt
    assert "=== SOURCE: paper-1 ===" in prompt
    assert "=== END OF CORPUS ===" in prompt


def test_run_synthesis_handles_missing_key_empty_corpus_and_success(tmp_path, monkeypatch):
    no_key = DistillConfig(distill_output_dir=tmp_path / "lib")
    assert run_synthesis(["ai"], "ctx", "demo", no_key) is None

    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr("distill.synthesize.gather_topic_files", lambda *_args, **_kwargs: [])
    assert run_synthesis(["ai"], "ctx", "demo", config) is None

    monkeypatch.setattr(
        "distill.synthesize.gather_topic_files",
        lambda *_args, **_kwargs: [("doc", "body")],
    )
    monkeypatch.setattr("distill.synthesize._get_client", lambda _config: object())
    monkeypatch.setattr("distill.synthesize._call_grok", lambda *_args, **_kwargs: "")
    assert run_synthesis(["ai"], "ctx", "demo", config) is None

    tracker = CostTracker()
    monkeypatch.setattr(
        "distill.synthesize._call_grok", lambda *_args, **_kwargs: "final synthesis"
    )
    result = run_synthesis(["ai"], "ctx", "demo", config, tracker=tracker)

    assert result is not None
    assert result.read_text(encoding="utf-8") == "final synthesis"
