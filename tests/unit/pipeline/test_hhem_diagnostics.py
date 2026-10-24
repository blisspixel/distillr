import logging
import sys
from types import SimpleNamespace

import pytest

from distill.pipeline import verify_entailment
from distill.pipeline.verify_entailment import HHEMChecker

CONFIG_MESSAGE = "You are using a model of type HHEMv2Config to instantiate a model of type HHEMv2. This is not supported for all configurations of models and can yield errors."
LENGTH_MESSAGE = "Token indices sequence length is longer than the specified maximum sequence length for this model (1542 > 512). Running this sequence through the model will result in indexing errors"


def test_only_verified_pinned_diagnostics_move_to_debug_and_input_is_complete(monkeypatch, caplog):
    configuration = logging.getLogger("transformers.configuration_utils")
    tokenization = logging.getLogger("transformers.tokenization_utils_base")
    seen = []

    class Model:
        def predict(self, pairs):
            seen.extend(pairs)
            tokenization.warning(LENGTH_MESSAGE)
            tokenization.warning("Unexpected tokenizer failure")
            return [0.9]

    class Loader:
        @staticmethod
        def from_pretrained(model, **kwargs):
            assert kwargs["revision"] == "de9a5e6ba9ba49531a022dba17e35ffeb2a6fad8"
            configuration.warning(CONFIG_MESSAGE)
            return Model()

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoModelForSequenceClassification=Loader,
            AutoConfig=SimpleNamespace(
                from_pretrained=lambda *a, **k: SimpleNamespace(foundation="google/flan-t5-base")
            ),
        ),
    )
    monkeypatch.setattr(verify_entailment, "_pinned_foundation_config", lambda config: config)
    with caplog.at_level(logging.DEBUG):
        checker = HHEMChecker()
        evidence = "full source " * 1000 + "tail evidence"
        assert checker.score(evidence, "tail claim") == 0.9
    assert seen == [(evidence, "tail claim")]
    assert (
        sum(r.levelno == logging.DEBUG and "Pinned HHEM" in r.message for r in caplog.records) == 2
    )
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == ["Unexpected tokenizer failure"]
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        configuration.warning(CONFIG_MESSAGE)
    assert CONFIG_MESSAGE in caplog.text


def test_foundation_config_is_bound_to_reviewed_snapshot_without_weights(monkeypatch, tmp_path):
    calls = []

    def snapshot(**kwargs):
        calls.append(kwargs)
        return str(tmp_path)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot))
    config = SimpleNamespace(foundation="google/flan-t5-base")
    for filename in verify_entailment._FOUNDATION_FILES:
        (tmp_path / filename).write_text("fixture", encoding="utf-8")
    assert verify_entailment._pinned_foundation_config(config) is config
    assert config.foundation == str(tmp_path)
    assert len(calls) == 1 and calls[0]["local_files_only"] is True
    assert calls[0]["revision"] == "7bcac572ce56db69c1ea7c8af255c5d7c9672fc2"
    assert calls[0]["repo_id"] == "google/flan-t5-base"
    assert set(calls[0]["allow_patterns"]) == {
        "config.json",
        "tokenizer_config.json",
        "tokenizer.json",
        "spiece.model",
        "special_tokens_map.json",
        "added_tokens.json",
    }


def test_unexpected_foundation_refuses_before_downloading(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=lambda **k: pytest.fail("unexpected model was fetched")),
    )
    with pytest.raises(ValueError, match="unexpected foundation"):
        verify_entailment._pinned_foundation_config(SimpleNamespace(foundation="attacker/model"))


def test_non_path_snapshot_response_refuses(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=lambda **k: None)
    )
    with pytest.raises(ValueError, match="local directory"):
        verify_entailment._pinned_foundation_config(
            SimpleNamespace(foundation="google/flan-t5-base")
        )


def test_loader_rejects_a_config_without_foundation_before_model_loading(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoConfig=SimpleNamespace(from_pretrained=lambda *a, **k: object()),
            AutoModelForSequenceClassification=SimpleNamespace(
                from_pretrained=lambda *a, **k: pytest.fail("invalid config reached model loader")
            ),
        ),
    )
    with pytest.raises(ValueError, match="no foundation identity"):
        HHEMChecker()


@pytest.mark.parametrize("cache", ["missing", "partial"])
def test_missing_or_partial_foundation_cache_fetches_only_the_pinned_snapshot(
    monkeypatch, tmp_path, cache
):
    calls = []

    def snapshot(**kwargs):
        calls.append(kwargs)
        if kwargs["local_files_only"] and cache == "missing":
            raise FileNotFoundError("not cached")
        return str(tmp_path)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot))
    config = SimpleNamespace(foundation="google/flan-t5-base")
    verify_entailment._pinned_foundation_config(config)
    assert [call["local_files_only"] for call in calls] == [True, False]
    assert all(call["revision"] == verify_entailment._FOUNDATION_REVISION for call in calls)
