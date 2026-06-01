# Eval Suite

Quality gate for local model validation. Compares local model output against cloud baselines.

> For interactive **cost × quality model selection** (sweep several models over frozen
> fixtures, advisory LLM-judge, recommendation), use the newer `distill eval` command and
> the `distill/eval/` package — see [`docs/usage.md`](../../docs/usage.md#evaluate-models-cost--quality).
> This suite remains the quick local-vs-cloud check used by `distill doctor --eval`.

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
