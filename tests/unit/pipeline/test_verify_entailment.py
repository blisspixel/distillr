"""Tests for the entailment verify tier (0.13.0).

All tests run with a mock checker -- CI never installs the optional extra or
downloads a model. Live HHEM validation happens opt-in on a dev box.
Design: docs/design/entailment-tier.md.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from distill.pipeline.verify import run_verify_hook, verify_insight, write_verify_sidecar
from distill.pipeline.verify_entailment import (
    EntailmentReport,
    chunk_evidence,
    evaluate_entailment,
    extract_entailment_claims,
    resolve_entailment_threshold,
)


class FakeChecker:
    """Scores by substring containment: evidence containing a marker supports."""

    model_name = "fake-checker"

    def __init__(self, supported_markers: tuple[str, ...] = ()):
        self.markers = supported_markers
        self.calls: list[tuple[str, str]] = []

    def score(self, evidence: str, claim: str) -> float:
        self.calls.append((evidence, claim))
        return 0.9 if any(m in claim and m in evidence for m in self.markers) else 0.1


def test_entailment_checker_initializes_once_across_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import distill.pipeline.verify as verify_mod

    checker = FakeChecker()
    start = threading.Barrier(4)
    release_loader = threading.Event()
    loader_entered = threading.Event()
    second_loader = threading.Event()
    count_lock = threading.Lock()
    load_count = 0

    def load_checker() -> FakeChecker:
        nonlocal load_count
        with count_lock:
            load_count += 1
            if load_count > 1:
                second_loader.set()
        loader_entered.set()
        assert release_loader.wait(timeout=5)
        return checker

    def get_checker() -> object:
        start.wait(timeout=5)
        return verify_mod._entailment_checker()

    monkeypatch.setattr(verify_mod, "_checker", None)
    monkeypatch.setattr(verify_mod, "_checker_loaded", False)
    monkeypatch.setattr(verify_mod, "load_default_checker", load_checker)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(get_checker) for _ in range(4)]
        assert loader_entered.wait(timeout=5)
        try:
            assert not second_loader.wait(timeout=0.2)
        finally:
            release_loader.set()
        assert [future.result(timeout=5) for future in futures] == [checker] * 4

    assert load_count == 1


_INSIGHT = """---
title: "x"
---

### Core Contribution

- RoMem replaces discrete timestamp lookup tables with continuous phase rotation across the graph.
- The semantic speed gate learns relational volatility directly from text embeddings of each relation.

### Limits

- short line
"""

_SOURCE = (
    "We introduce RoMem, which replaces discrete timestamp lookup tables with "
    "continuous phase rotation across the graph. " * 10
)


class TestClaimExtraction:
    def test_bullets_become_claims_short_lines_skipped(self):
        claims = extract_entailment_claims(_INSIGHT)
        texts = [c.text for c in claims]
        assert len(texts) == 2
        assert texts[0].startswith("RoMem replaces discrete")
        assert all("short line" not in t for t in texts)

    def test_headings_fences_and_urls_excluded(self):
        body = (
            "## A heading long enough to look like a prose claim if not excluded\n"
            "```\nthis fenced line is long enough to be a claim but lives in code\n```\n"
            "- A real claim about the system architecture that is plenty long enough\n"
        )
        claims = extract_entailment_claims(body)
        assert len(claims) == 1
        assert claims[0].text.startswith("A real claim")

    def test_unclosed_fence_does_not_hide_later_claims(self):
        body = (
            "```\nThe model reached ninety-nine percent accuracy on a public benchmark in 2026.\n"
        )
        claims = extract_entailment_claims(body)
        assert len(claims) == 1
        assert "ninety-nine percent" in claims[0].text

    def test_open_questions_are_not_treated_as_claims(self):
        body = (
            "## Open Questions\n"
            "- Which orchestration service should own retries and backpressure?\n"
            "- The external harness owns retries and backpressure in production.\n"
        )

        claims = extract_entailment_claims(body)

        assert [claim.text for claim in claims] == [
            "The external harness owns retries and backpressure in production."
        ]

    def test_markdown_markers_do_not_distort_claim_text(self):
        body = (
            "- **Installations**: Run `pip install langgraph` or "
            "`uv add langgraph` for the local package.\n"
        )

        claims = extract_entailment_claims(body)

        assert [claim.text for claim in claims] == [
            "Installations: Run pip install langgraph or uv add langgraph for the local package."
        ]


class TestChunking:
    def test_short_source_is_one_chunk(self):
        assert chunk_evidence("short text") == ["short text"]

    def test_long_source_overlaps(self):
        text = "word " * 1000  # ~5000 chars
        chunks = chunk_evidence(text)
        assert len(chunks) > 2
        # 50% overlap: consecutive chunks share content.
        assert chunks[0][-100:] in chunks[1] or chunks[1][:100] in chunks[0]

    def test_empty_source_no_chunks(self):
        assert chunk_evidence("   ") == []


class TestEvaluate:
    def test_supported_claims_pass_unsupported_flag(self):
        checker = FakeChecker(supported_markers=("phase rotation",))
        report = evaluate_entailment(_INSIGHT, _SOURCE, checker, threshold=0.5)
        assert report.checked == 2
        assert len(report.flagged) == 1  # the speed-gate claim has no support
        assert "semantic speed gate" in report.flagged[0]["claim"]
        assert report.flagged[0]["score"] == 0.1
        assert report.model == "fake-checker"

    def test_no_claims_or_no_evidence_is_empty_report(self):
        checker = FakeChecker()
        assert evaluate_entailment("- tiny", _SOURCE, checker).checked == 0
        assert evaluate_entailment(_INSIGHT, "", checker).checked == 0
        assert checker.calls == []

    def test_threshold_resolution(self, monkeypatch):
        assert resolve_entailment_threshold("0.7") == 0.7
        assert resolve_entailment_threshold("nonsense") == 0.5
        assert resolve_entailment_threshold("1.5") == 0.5
        monkeypatch.setenv("DISTILL_ENTAILMENT_THRESHOLD", "0.3")
        assert resolve_entailment_threshold() == 0.3


class TestSidecarV2:
    def test_entailment_block_is_additive(self, tmp_path):
        report = verify_insight("- claim with 72.6 score", "source has 72.6", mode="warn")
        ent = EntailmentReport(
            checked=2,
            flagged=({"claim": "c", "score": 0.1, "best_chunk_preview": "p"},),
            model="fake",
            threshold=0.5,
        )
        path = write_verify_sidecar(tmp_path, report, entailment=ent)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 3
        assert data["entailment"]["status"] == "flagged"
        assert data["entailment"]["checked"] == 2
        assert data["entailment"]["flagged"][0]["claim"] == "c"

    def test_block_absent_when_tier_not_run(self, tmp_path):
        report = verify_insight("- a 72.6 claim", "72.6", mode="warn")
        path = write_verify_sidecar(tmp_path, report)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "entailment" not in data

    def test_sidecar_rejects_passed_status_without_a_report(self, tmp_path):
        report = verify_insight("- a 72.6 claim", "72.6", mode="strict")

        with pytest.raises(ValueError, match="complete clean report"):
            write_verify_sidecar(tmp_path, report, entailment_status="passed")


class TestHookIntegration:
    def test_hook_includes_entailment_when_checker_available(self, tmp_path, monkeypatch):
        import distill.pipeline.verify as verify_mod

        checker = FakeChecker(supported_markers=("phase rotation",))
        monkeypatch.setattr(verify_mod, "_checker", checker)
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)

        outcome = run_verify_hook(tmp_path, _INSIGHT, _SOURCE, mode="warn", insight_name="i.md")

        assert outcome is not None
        assert outcome.entailment is not None
        assert outcome.entailment.checked == 2
        assert outcome.has_flags
        assert "prose claim(s)" in outcome.summary_line
        data = json.loads(outcome.sidecar.read_text(encoding="utf-8"))
        assert data["entailment"]["model"] == "fake-checker"

    def test_strict_refuses_on_entailment_flags_alone(self, tmp_path, monkeypatch):
        import distill.pipeline.verify as verify_mod

        checker = FakeChecker()  # supports nothing -> every claim flags
        monkeypatch.setattr(verify_mod, "_checker", checker)
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)

        outcome = run_verify_hook(tmp_path, _INSIGHT, _SOURCE, mode="strict", insight_name="i.md")

        assert outcome is not None
        assert outcome.report.ok  # no numeric flags
        assert outcome.has_flags
        assert outcome.refused  # but prose flags refuse in strict mode

    def test_hook_unchanged_when_checker_absent(self, tmp_path, monkeypatch):
        import distill.pipeline.verify as verify_mod

        monkeypatch.setattr(verify_mod, "_checker", None)
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)

        outcome = run_verify_hook(tmp_path, _INSIGHT, _SOURCE, mode="warn")

        assert outcome is not None
        assert outcome.entailment is None
        data = json.loads(outcome.sidecar.read_text(encoding="utf-8"))
        assert "entailment" not in data

    def test_checker_crash_never_kills_the_run(self, tmp_path, monkeypatch):
        import distill.pipeline.verify as verify_mod

        class ExplodingChecker:
            model_name = "boom"

            def score(self, evidence: str, claim: str) -> float:
                raise RuntimeError("model exploded")

        monkeypatch.setattr(verify_mod, "_checker", ExplodingChecker())
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)

        outcome = run_verify_hook(tmp_path, _INSIGHT, _SOURCE, mode="warn")

        assert outcome is not None
        assert outcome.entailment is None  # tier skipped, deterministic stands

    def test_required_entailment_refuses_when_checker_is_unavailable(self, tmp_path, monkeypatch):
        import distill.pipeline.verify as verify_mod

        monkeypatch.setattr(verify_mod, "_checker", None)
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)

        outcome = run_verify_hook(
            tmp_path,
            _INSIGHT,
            _SOURCE,
            mode="strict",
            require_entailment=True,
        )

        assert outcome is not None
        assert outcome.refused
        assert outcome.entailment_status == "unavailable"
        data = json.loads(outcome.sidecar.read_text(encoding="utf-8"))
        assert data["entailment"] == {
            "status": "unavailable",
            "checked": 0,
            "supported": 0,
            "flagged": [],
            "model": "",
            "threshold": None,
            "reason": "checker unavailable",
        }

    def test_required_entailment_refuses_checker_failure(self, tmp_path, monkeypatch):
        import distill.pipeline.verify as verify_mod

        class ExplodingChecker:
            model_name = "boom"

            def score(self, evidence: str, claim: str) -> float:
                raise RuntimeError("model exploded")

        monkeypatch.setattr(verify_mod, "_checker", ExplodingChecker())
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)

        outcome = run_verify_hook(
            tmp_path,
            _INSIGHT,
            _SOURCE,
            mode="strict",
            require_entailment=True,
        )

        assert outcome is not None
        assert outcome.refused
        assert outcome.entailment_status == "error"
        data = json.loads(outcome.sidecar.read_text(encoding="utf-8"))
        assert data["entailment"]["status"] == "error"
        assert data["entailment"]["reason"] == "checker evaluation failed"

    def test_required_entailment_refuses_zero_claim_coverage(self, tmp_path, monkeypatch):
        import distill.pipeline.verify as verify_mod

        monkeypatch.setattr(verify_mod, "_checker", FakeChecker())
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)

        outcome = run_verify_hook(
            tmp_path,
            "Brief claim.",
            _SOURCE,
            mode="strict",
            require_entailment=True,
        )

        assert outcome is not None
        assert outcome.refused
        assert outcome.entailment_status == "incomplete"
        data = json.loads(outcome.sidecar.read_text(encoding="utf-8"))
        assert data["entailment"]["status"] == "incomplete"
        assert data["entailment"]["checked"] == 0

    def test_required_entailment_passes_only_complete_clean_report(self, tmp_path, monkeypatch):
        import distill.pipeline.verify as verify_mod

        checker = FakeChecker(supported_markers=("phase rotation",))
        monkeypatch.setattr(verify_mod, "_checker", checker)
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)

        outcome = run_verify_hook(
            tmp_path,
            "- RoMem replaces discrete timestamp lookup tables with continuous phase rotation.",
            _SOURCE,
            mode="strict",
            require_entailment=True,
        )

        assert outcome is not None
        assert not outcome.refused
        assert outcome.entailment_status == "passed"
        data = json.loads(outcome.sidecar.read_text(encoding="utf-8"))
        assert data["entailment"]["status"] == "passed"
        assert data["entailment"]["checked"] == 1


class TestAuditRollup:
    def test_entailment_flags_count_in_verify_rollup(self, tmp_path):
        from distill.pipeline.audit import collect_verify_rollup

        d = tmp_path / "papers" / "p1"
        d.mkdir(parents=True)
        (d / "p1_Insights.md").write_text("---\n---\nbody", encoding="utf-8")
        (d / "p1_Verify.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "mode": "warn",
                    "checked": 0,
                    "supported": 0,
                    "unsupported": [],
                    "entailment": {
                        "checked": 3,
                        "supported": 2,
                        "flagged": [
                            {"claim": "wrong claim", "score": 0.2, "best_chunk_preview": "..."}
                        ],
                        "model": "fake",
                        "threshold": 0.5,
                    },
                }
            ),
            encoding="utf-8",
        )

        rollup = collect_verify_rollup(tmp_path)

        assert rollup.checked == 1
        assert rollup.clean == 0
        assert len(rollup.flagged) == 1
        assert rollup.flagged[0]["kind"] == "entailment"
        assert rollup.flagged[0]["token"] == "wrong claim"
