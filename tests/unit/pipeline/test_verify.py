"""Tests for distill.pipeline.verify (write-time claim grounding, deterministic tier)."""

from __future__ import annotations

import json

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

    def test_strict_degrades_to_warn_until_implemented(self):
        assert resolve_verify_mode("strict") == "warn"


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

    def test_hook_warn_mode_returns_report_and_writes_sidecar(self, tmp_path):
        result = run_verify_hook(tmp_path, "Scores 99.9.", "has 72.6", mode="warn")
        assert result is not None
        report, sidecar = result
        assert not report.ok
        assert sidecar.exists()

    def test_hook_clean_insight_still_writes_positive_sidecar(self, tmp_path):
        result = run_verify_hook(tmp_path, "Scores 72.6 MRR.", "scores 72.6", mode="warn")
        assert result is not None
        report, sidecar = result
        assert report.ok
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["unsupported"] == []


# ---- wiring: paper emit path -------------------------------------------------


def test_paper_write_runs_verify_hook(tmp_path, monkeypatch):
    """_write_paper_artifacts grounds the insight against the paper doc and
    leaves a _Verify.json sidecar beside the insight artifact."""
    from distill import _cli_impl
    from distill.config import DistillConfig
    from distill.ingestors.papers.arxiv import PaperRecord

    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    record = PaperRecord(paper_id="2601.00001v1", title="T", abstract="a")

    paper_dir = _cli_impl._write_paper_artifacts(
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
    from distill import _cli_impl
    from distill.config import DistillConfig
    from distill.ingestors.papers.arxiv import PaperRecord

    config = DistillConfig(
        xai_api_key="t", distill_output_dir=tmp_path / "library", distill_verify="off"
    )
    record = PaperRecord(paper_id="2601.00002v1", title="T2", abstract="a")

    paper_dir = _cli_impl._write_paper_artifacts(
        "tkg", record, config, insights="- 99.9 MRR.", document="72.6 MRR."
    )

    assert list(paper_dir.glob("*_Verify.json")) == []


def test_numeric_claim_is_frozen():
    claim = NumericClaim(token="1.0", kind="decimal", context="x")
    try:
        claim.token = "2.0"  # type: ignore[misc]
        raise AssertionError("expected FrozenInstanceError")
    except Exception:
        pass
