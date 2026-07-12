# Legacy structural eval support

This directory contains the deterministic structural scorer and frozen fixture
used by its unit tests. It is not the public live-model evaluation command and
does not generate model output.

For cost and quality model selection over frozen product fixtures, use
`distill eval` and the `distill/eval/` package. See
[`docs/usage.md`](../../docs/usage.md#evaluate-models-cost--quality).

Run the legacy scorer tests with:

```bash
uv run pytest -q tests/eval tests/unit/doctor/test_quality_gate.py
```

## Threshold

A supplied output passes this legacy helper when its mean structural score is
at least 80%. This threshold is test support, not the `distill eval` migration
gate. The helper measures:

- Structural completeness (all expected sections present)
- Key concept coverage (named entities and techniques mentioned)
- Depth (word count per section relative to baseline)
- Markdown formatting
