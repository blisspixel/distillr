"""Tests for distill.pipeline.verify (write-time claim grounding, deterministic tier)."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.pipeline.verify import (
    NumericClaim,
    extract_numeric_claims,
    resolve_verify_mode,
    run_verify_hook,
    verify_insight,
    write_verify_sidecar,
)

# ---- extraction --------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    return [c.token for c in extract_numeric_claims(text)]


@given(text=st.text(max_size=500))
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_extract_numeric_claims_fuzz_no_crash_and_well_formed(text: str) -> None:
    # Extraction runs over untrusted markdown; arbitrary input must not crash or
    # hang (ReDoS) and the output must be well-formed. The deal.post contract on
    # extract_numeric_claims also enforces the well-formedness at runtime.
    for claim in extract_numeric_claims(text):
        assert claim.token
        assert claim.kind in {"money", "percent", "decimal", "integer", "year"}


class TestExtraction:
    def test_extracts_the_load_bearing_shapes(self):
        text = (
            "Reaches 72.6 MRR and 0.878 ROC-AUC (a 47.33% gain) over 15,514 claims "
            "from 2024, costing $200."
        )
        assert _tokens(text) == ["72.6", "0.878", "47.33%", "15,514", "2024", "$200"]

    def test_small_bare_integers_are_not_claims(self):
        # List numbers, rankings, "3 methods" would drown the signal.
        assert _tokens("We compare 3 methods across 12 runs in section 7.") == []

    def test_unit_bearing_small_integers_are_claims(self):
        text = (
            "Uses a 240W supply, runs from 5°C to 30°C, supports 200 billion "
            "parameters or 405B when linked, and has 128 GB memory at 1 PFLOP."
        )
        assert _tokens(text) == ["240", "5", "30", "200", "405", "128", "1"]

    def test_skips_frontmatter(self):
        text = '---\ntitle: "x"\nduration_seconds: 600\n---\n\nScore was 0.91.'
        assert _tokens(text) == ["0.91"]

    def test_skips_fenced_code_blocks(self):
        text = "```\nf1 = 99.9\n```\nReal claim: 88.8 accuracy."
        assert _tokens(text) == ["88.8"]

    def test_skips_urls_and_link_targets(self):
        text = "See [the paper](https://arxiv.org/abs/2604.11544v1) and https://x.test/9.99 -- 0.5 score."
        assert _tokens(text) == ["0.5"]

    def test_skips_arxiv_shaped_identifiers(self):
        assert _tokens("RoMem (arXiv:2604.11544) shows 72.6 MRR.") == ["72.6"]

    def test_years_are_classified_as_years(self):
        claims = extract_numeric_claims("Published in 2026.")
        assert [(c.token, c.kind) for c in claims] == [("2026", "year")]

    def test_context_line_is_carried(self):
        claims = extract_numeric_claims("- Reaches 72.6 MRR on ICEWS")
        assert claims[0].context == "- Reaches 72.6 MRR on ICEWS"


# ---- grounding ---------------------------------------------------------------


class TestGrounding:
    def test_exact_match_supported(self):
        report = verify_insight("Scores 72.6 MRR.", "the model scores 72.6 MRR overall")
        assert report.ok and report.checked == 1

    def test_unsupported_number_is_flagged(self):
        report = verify_insight("Scores 99.9 MRR.", "the model scores 72.6 MRR overall")
        assert not report.ok
        assert report.unsupported[0].token == "99.9"

    def test_comma_and_space_thousands_normalize(self):
        assert verify_insight("Over 15,514 claims.", "a corpus of 15514 claims").ok
        assert verify_insight("Over 15,514 claims.", "a corpus of 15 514 claims").ok

    def test_percent_sign_mismatch_still_supported(self):
        assert verify_insight("A 47.33% gain.", "improves by 47.33 points").ok

    def test_rounding_within_half_ulp_supported(self):
        # Model legitimately rounds 0.878 -> 0.88.
        assert verify_insight("Reaches 0.88 ROC-AUC.", "ROC-AUC of 0.878").ok

    def test_rounding_beyond_half_ulp_flagged(self):
        assert not verify_insight("Reaches 0.87 ROC-AUC.", "ROC-AUC of 0.878").ok

    def test_years_require_exact_match(self):
        # No rounding tolerance for years: 2025 is not "approximately 2026".
        assert not verify_insight("Published in 2026.", "released in 2025").ok
        assert verify_insight("Published in 2026.", "released June 2026").ok

    def test_money_matches_bare_number(self):
        assert verify_insight("Costs $200 per run.", "a budget of 200 dollars").ok

    def test_unit_bearing_numbers_match_source_numbers(self):
        insight = "Uses a 240W supply and supports 200 billion parameters."
        source = "Power Supply 240 Watts. Support for AI models up to 200 billion parameters."
        report = verify_insight(insight, source)
        assert report.ok
        assert report.checked == 2

    def test_repeated_unsupported_token_flagged_once(self):
        report = verify_insight("Got 99.9. Again 99.9.", "source has 1.0 only")
        assert report.checked == 2
        assert len(report.unsupported) == 1

    def test_supported_property(self):
        report = verify_insight("72.6 and 99.9.", "72.6")
        assert report.checked == 2
        assert report.supported == 1


# ---- mode resolution ---------------------------------------------------------


class TestModeResolution:
    def test_off(self):
        assert resolve_verify_mode("off") == "off"
        assert resolve_verify_mode(" OFF ") == "off"

    def test_warn_default_and_unknown_degrade_to_warn(self):
        assert resolve_verify_mode("warn") == "warn"
        assert resolve_verify_mode("") == "warn"
        assert resolve_verify_mode("bogus") == "warn"

    def test_strict_is_honored(self):
        assert resolve_verify_mode("strict") == "strict"
        assert resolve_verify_mode(" STRICT ") == "strict"


# ---- sidecar + hook ----------------------------------------------------------


class TestSidecarAndHook:
    def test_sidecar_written_with_payload(self, tmp_path):
        report = verify_insight("Scores 99.9 MRR.", "scores 72.6")
        path = write_verify_sidecar(
            tmp_path, report, insight_name="x_Insights.md", source_name="x_Paper.md"
        )
        assert path.name.endswith("_Verify.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["checked"] == 1
        assert data["supported"] == 0
        assert data["unsupported"][0]["token"] == "99.9"
        assert data["insight"] == "x_Insights.md"

    def test_hook_off_mode_writes_nothing(self, tmp_path):
        assert run_verify_hook(tmp_path, "x 99.9", "source", mode="off") is None
        assert list(tmp_path.iterdir()) == []

    def test_hook_empty_source_writes_nothing(self, tmp_path):
        assert run_verify_hook(tmp_path, "x 99.9", "   ", mode="warn") is None

    def test_hook_warn_mode_returns_outcome_and_writes_sidecar(self, tmp_path):
        outcome = run_verify_hook(tmp_path, "Scores 99.9.", "has 72.6", mode="warn")
        assert outcome is not None
        assert not outcome.report.ok
        assert outcome.sidecar.exists()
        assert not outcome.refused  # warn never refuses
        assert "lack source support" in outcome.summary_line

    def test_hook_clean_insight_still_writes_positive_sidecar(self, tmp_path):
        outcome = run_verify_hook(tmp_path, "Scores 72.6 MRR.", "scores 72.6", mode="warn")
        assert outcome is not None
        assert outcome.report.ok
        data = json.loads(outcome.sidecar.read_text(encoding="utf-8"))
        assert data["unsupported"] == []

    def test_hook_strict_with_flags_refuses(self, tmp_path):
        outcome = run_verify_hook(
            tmp_path, "Scores 99.9.", "has 72.6", mode="strict", insight_name="x_Insights.md"
        )
        assert outcome is not None
        assert outcome.refused
        assert "refused x_Insights.md" in outcome.summary_line
        assert outcome.sidecar.exists()  # the sidecar records why

    def test_hook_strict_clean_does_not_refuse(self, tmp_path):
        outcome = run_verify_hook(tmp_path, "Scores 72.6.", "has 72.6", mode="strict")
        assert outcome is not None
        assert not outcome.refused


# ---- wiring: paper emit path -------------------------------------------------


def test_paper_write_runs_verify_hook(tmp_path, monkeypatch):
    """write_paper_artifacts grounds the insight against the paper doc and
    leaves a _Verify.json sidecar beside the insight artifact."""
    from distill.commands._paper_artifacts import write_paper_artifacts
    from distill.config import DistillConfig
    from distill.ingestors.papers.arxiv import PaperRecord

    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    record = PaperRecord(paper_id="2601.00001v1", title="T", abstract="a")

    paper_dir = write_paper_artifacts(
        "tkg",
        record,
        config,
        insights="### Core\n- Reaches 99.9 MRR on ICEWS.",
        document="The model reaches 72.6 MRR on ICEWS05-15.",
    )

    sidecars = list(paper_dir.glob("*_Verify.json"))
    assert len(sidecars) == 1
    data = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert data["unsupported"][0]["token"] == "99.9"
    # warn mode: the insight artifact is still written.
    assert list(paper_dir.glob("*_Insights.md"))


def test_paper_write_verify_off_skips_sidecar(tmp_path, monkeypatch):
    from distill.commands._paper_artifacts import write_paper_artifacts
    from distill.config import DistillConfig
    from distill.ingestors.papers.arxiv import PaperRecord

    config = DistillConfig(
        xai_api_key="t", distill_output_dir=tmp_path / "library", distill_verify="off"
    )
    record = PaperRecord(paper_id="2601.00002v1", title="T2", abstract="a")

    paper_dir = write_paper_artifacts(
        "tkg", record, config, insights="- 99.9 MRR.", document="72.6 MRR."
    )

    assert list(paper_dir.glob("*_Verify.json")) == []


def test_paper_write_strict_refuses_insight_but_keeps_receipt(tmp_path):
    """Strict mode: the unsupported insight is NOT committed; the paper doc
    (the receipt) and the sidecar (the why) still are."""
    from distill.commands._paper_artifacts import write_paper_artifacts
    from distill.config import DistillConfig
    from distill.ingestors.papers.arxiv import PaperRecord

    config = DistillConfig(
        xai_api_key="t", distill_output_dir=tmp_path / "library", distill_verify="strict"
    )
    record = PaperRecord(paper_id="2601.00003v1", title="T3", abstract="a")

    paper_dir = write_paper_artifacts(
        "tkg", record, config, insights="- Reaches 99.9 MRR.", document="reaches 72.6 MRR."
    )

    assert list(paper_dir.glob("*_Insights.md")) == []
    assert list(paper_dir.glob("*_Paper.md"))  # receipt kept
    sidecars = list(paper_dir.glob("*_Verify.json"))
    assert len(sidecars) == 1
    assert json.loads(sidecars[0].read_text(encoding="utf-8"))["mode"] == "strict"


def test_paper_write_strict_clean_insight_is_written(tmp_path):
    from distill.commands._paper_artifacts import write_paper_artifacts
    from distill.config import DistillConfig
    from distill.ingestors.papers.arxiv import PaperRecord

    config = DistillConfig(
        xai_api_key="t", distill_output_dir=tmp_path / "library", distill_verify="strict"
    )
    record = PaperRecord(paper_id="2601.00004v1", title="T4", abstract="a")

    paper_dir = write_paper_artifacts(
        "tkg", record, config, insights="- Reaches 72.6 MRR.", document="reaches 72.6 MRR."
    )

    assert list(paper_dir.glob("*_Insights.md"))


def test_local_ingest_strict_refuses_insight(tmp_path, monkeypatch):
    """The local-file emit path honors strict refusal end to end."""
    from distill.config import DistillConfig
    from distill.llm.router import LLM_Response
    from distill.pipeline.analysis import local as local_mod

    monkeypatch.setattr(
        local_mod,
        "llm_call",
        lambda rc, **kwargs: LLM_Response(
            text="### Claims\n- The benchmark hits 99.9 accuracy.",
            input_tokens=1,
            output_tokens=1,
            model="grok-4.3",
        ),
    )
    config = DistillConfig(
        xai_api_key="t", distill_output_dir=tmp_path / "library", distill_verify="strict"
    )
    doc = tmp_path / "notes.md"
    doc.write_text("The benchmark hits 72.6 accuracy.", encoding="utf-8")

    result = local_mod.ingest_local_file(doc, topic="tkg", config=config)

    assert result.insights_path is None
    local_dirs = list((config.library_dir / "topics" / "tkg" / "local").iterdir())
    assert len(local_dirs) == 1
    assert list(local_dirs[0].glob("*_Verify.json"))
    assert list(local_dirs[0].glob("*_Content.md"))  # receipt kept


def test_local_ingest_reports_prose_only_refusal(tmp_path, monkeypatch, capsys):
    """A semantic-only strict refusal must be visible to CLI callers."""
    from distill.config import DistillConfig
    from distill.llm.router import LLM_Response
    from distill.pipeline import verify as verify_mod
    from distill.pipeline.analysis import local as local_mod

    class FlaggingChecker:
        model_name = "flagging-checker"

        def score(self, evidence: str, claim: str) -> float:
            return 0.1

    monkeypatch.setattr(verify_mod, "_checker", FlaggingChecker())
    monkeypatch.setattr(verify_mod, "_checker_loaded", True)
    monkeypatch.setattr(
        local_mod,
        "llm_call",
        lambda rc, **kwargs: LLM_Response(
            text=(
                "- The external scheduler always guarantees perfect delivery for every agent task."
            ),
            input_tokens=1,
            output_tokens=1,
            model="grok-4.3",
        ),
    )
    config = DistillConfig(
        xai_api_key="t", distill_output_dir=tmp_path / "library", distill_verify="strict"
    )
    doc = tmp_path / "notes.md"
    doc.write_text("External schedulers coordinate task delivery.", encoding="utf-8")

    result = local_mod.ingest_local_file(doc, topic="tkg", config=config)

    assert result.insights_path is None
    output = capsys.readouterr().out
    assert "verify strict: refused" in output
    assert "1 prose claim(s)" in output


def test_apply_verify_override_sets_env_and_rejects_typos(monkeypatch):
    import typer

    from distill.commands._helpers import _apply_verify_override

    monkeypatch.delenv("DISTILL_VERIFY", raising=False)
    _apply_verify_override("STRICT")
    import os

    assert os.environ["DISTILL_VERIFY"] == "strict"
    monkeypatch.delenv("DISTILL_VERIFY", raising=False)

    _apply_verify_override("")  # no-op
    assert "DISTILL_VERIFY" not in os.environ

    try:
        _apply_verify_override("bogus")
        raise AssertionError("expected typer.Exit")
    except typer.Exit:
        pass


def test_numeric_claim_is_frozen():
    claim = NumericClaim(token="1.0", kind="decimal", context="x")
    try:
        claim.token = "2.0"  # type: ignore[misc]
        raise AssertionError("expected FrozenInstanceError")
    except Exception:
        pass


def test_run_synthesis_verify_hits_notify_on_mismatch(tmp_path):
    """Covers the if not ok: notify branch (and return) in run_synthesis_verify."""
    from distill.pipeline.verify import run_synthesis_verify

    notified = []

    def n(s):
        notified.append(s)

    # mismatch claim -> not ok -> notify
    res = run_synthesis_verify(
        tmp_path,
        "The score is 99.9.",
        "The score is 72.6.",  # no 99.9
        verify_mode="warn",
        identity="i",
        insight_name="i.md",
        source_name="r.md",
        insight_sha256="0" * 64,
        notify=n,
    )
    assert len(notified) > 0
    assert res is False  # for warn mode

    from distill.library.paths import artifact_path

    stale = artifact_path(tmp_path, "verify", identity="i3", extension="json")
    stale.write_text('{"stale": true}', encoding="utf-8")

    # Off mode clears any prior verification claim before allowing the write.
    res_none = run_synthesis_verify(
        tmp_path,
        "synth",
        "receipt",
        verify_mode="off",
        identity="i3",
        insight_name="i3.md",
        source_name="r3.md",
        insight_sha256="1" * 64,
        notify=n,
    )
    assert res_none is False
    assert not stale.exists()


def test_run_synthesis_verify_strict_mismatch_refuses(tmp_path):
    """Covers strict mismatch path for refused=True in run_synthesis_verify (to hit remaining branch)."""
    from distill.pipeline.verify import run_synthesis_verify

    notified = []

    def n(s):
        notified.append(s)

    from distill.library.paths import artifact_path

    prior_sidecar = artifact_path(tmp_path, "verify", identity="i", extension="json")
    prior_content = '{"prior": "binding"}'
    prior_sidecar.write_text(prior_content, encoding="utf-8")

    res = run_synthesis_verify(
        tmp_path,
        "The score is 99.9.",
        "The score is 72.6.",
        verify_mode="strict",
        identity="i",
        insight_name="i.md",
        source_name="r.md",
        insight_sha256="0" * 64,
        notify=n,
    )
    assert res is True
    assert len(notified) > 0
    assert prior_sidecar.read_text(encoding="utf-8") == prior_content
    assert "previous artifact and verification sidecar retained" in notified[0]


def test_run_synthesis_verify_refuses_when_sidecar_cannot_be_published(tmp_path, monkeypatch):
    from distill.pipeline import verify as verify_module

    notified: list[str] = []
    monkeypatch.setattr(
        verify_module,
        "write_verify_sidecar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )

    refused = verify_module.run_synthesis_verify(
        tmp_path,
        "The score is 72.6.",
        "The score is 72.6.",
        verify_mode="warn",
        identity="i",
        insight_name="i.md",
        source_name="r.md",
        insight_sha256="0" * 64,
        notify=notified.append,
    )

    assert refused is True
    assert "could not be published" in notified[0]


@pytest.mark.parametrize("verify_mode", ["warn", "off"])
def test_verified_synthesis_restores_prior_sidecar_when_artifact_write_fails(
    tmp_path,
    monkeypatch,
    verify_mode: str,
) -> None:
    from distill.library.paths import artifact_path
    from distill.pipeline import verify as verify_module

    sidecar = artifact_path(tmp_path, "verify", identity="binding", extension="json")
    prior = b'{"prior": "binding"}\n'
    sidecar.write_bytes(prior)

    def fail_artifact(*_args, **_kwargs):
        raise OSError("artifact disk unavailable")

    monkeypatch.setattr(verify_module, "write_text_artifact", fail_artifact)

    with pytest.raises(OSError, match="artifact disk unavailable"):
        verify_module.write_verified_synthesis(
            tmp_path,
            "synthesis",
            "The score is 72.6.",
            "The score is 72.6.",
            verify_mode=verify_mode,
            artifact_identity="artifact",
            verify_identity="binding",
            source_name="receipt",
            notify=lambda _message: None,
        )

    assert sidecar.read_bytes() == prior


def test_verified_synthesis_removes_new_sidecar_when_artifact_write_fails(
    tmp_path,
    monkeypatch,
) -> None:
    from distill.library.paths import artifact_path
    from distill.pipeline import verify as verify_module

    sidecar = artifact_path(tmp_path, "verify", identity="binding", extension="json")

    def fail_artifact(*_args, **_kwargs):
        raise OSError("artifact disk unavailable")

    monkeypatch.setattr(verify_module, "write_text_artifact", fail_artifact)

    with pytest.raises(OSError, match="artifact disk unavailable"):
        verify_module.write_verified_synthesis(
            tmp_path,
            "synthesis",
            "The score is 72.6.",
            "The score is 72.6.",
            verify_mode="warn",
            artifact_identity="artifact",
            verify_identity="binding",
            source_name="receipt",
            notify=lambda _message: None,
        )

    assert not sidecar.exists()


def test_verified_synthesis_surfaces_artifact_and_sidecar_rollback_failures(
    tmp_path,
    monkeypatch,
) -> None:
    from distill.library.paths import artifact_path
    from distill.pipeline import verify as verify_module

    sidecar = artifact_path(tmp_path, "verify", identity="binding", extension="json")
    sidecar.write_text('{"prior": "binding"}\n', encoding="utf-8")

    def fail_artifact(*_args, **_kwargs):
        raise OSError("artifact disk unavailable")

    def fail_rollback(*_args, **_kwargs):
        raise OSError("sidecar disk unavailable")

    monkeypatch.setattr(verify_module, "write_text_artifact", fail_artifact)
    monkeypatch.setattr(verify_module, "atomic_write_confined_bytes", fail_rollback)

    with pytest.raises(ExceptionGroup, match="sidecar rollback failed") as caught:
        verify_module.write_verified_synthesis(
            tmp_path,
            "synthesis",
            "The score is 72.6.",
            "The score is 72.6.",
            verify_mode="warn",
            artifact_identity="artifact",
            verify_identity="binding",
            source_name="receipt",
            notify=lambda _message: None,
        )

    assert [str(error) for error in caught.value.exceptions] == [
        "artifact disk unavailable",
        "sidecar disk unavailable",
    ]


def test_concurrent_verified_synthesis_keeps_artifact_and_sidecar_bound(
    tmp_path,
    monkeypatch,
) -> None:
    from distill.library.insights import insight_content_sha256
    from distill.library.paths import artifact_path
    from distill.pipeline import verify as verify_module

    first_waiting = threading.Event()
    release_first = threading.Event()
    real_write = verify_module.write_text_artifact

    def blocking_write(directory, artifact_type, content, *, identity):
        if "111.1" in content:
            first_waiting.set()
            assert release_first.wait(timeout=5)
        return real_write(directory, artifact_type, content, identity=identity)

    def publish(score: str):
        return verify_module.write_verified_synthesis(
            tmp_path,
            "synthesis",
            f"The score is {score}.",
            f"The score is {score}.",
            verify_mode="warn",
            artifact_identity="same",
            verify_identity="same",
            source_name="receipt",
            notify=lambda _message: None,
        )

    monkeypatch.setattr(verify_module, "write_text_artifact", blocking_write)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(publish, "111.1")
        assert first_waiting.wait(timeout=5)
        second = executor.submit(publish, "222.2")
        with pytest.raises(FutureTimeoutError):
            second.result(timeout=0.25)
        release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)

    artifact = artifact_path(tmp_path, "synthesis", identity="same")
    sidecar = artifact_path(tmp_path, "verify", identity="same", extension="json")
    artifact_text = artifact.read_text(encoding="utf-8")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["insight_sha256"] == insight_content_sha256(artifact_text)
