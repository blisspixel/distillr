# Eval Suite

Quality gate for local model validation. Compares local model output against cloud baselines.

## Generating baselines

Run with cloud provider to generate reference outputs:

```bash
DISTILL_PROVIDER=xai python -m tests.eval.generate_baselines
```

## Running eval

Compare a local model against baselines:

```bash
distill doctor --eval --model qwen3.5:27b
```

## Threshold

A model passes if it achieves >= 80% of the cloud baseline quality score.
Quality is measured by:
- Structural completeness (all expected sections present)
- Key concept coverage (named entities and techniques mentioned)
- Depth (word count per section relative to baseline)
