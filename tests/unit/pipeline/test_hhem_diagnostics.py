import logging
import sys
from types import SimpleNamespace

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
            assert kwargs["revision"] == "8e4a2e6e96c708cc76c2344f7e4757df2515292c"
            configuration.warning(CONFIG_MESSAGE)
            return Model()

    monkeypatch.setitem(
        sys.modules, "transformers", SimpleNamespace(AutoModelForSequenceClassification=Loader)
    )
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
