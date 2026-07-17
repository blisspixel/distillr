# Gotchas from real failure modes

- Forgetting `--preview` before ingest or `distill discover` leads to surprise
  spend. Always preview and read the cost estimate.
- Stale syntheses or prompt versions produce confident but outdated prose.
  Run `distill audit <topic>` regularly; re-analyze or re-synthesize when
  flagged.
- Thin transcripts on long videos. The audit reports duration vs transcript
  length; do not trust analysis of videos where the transcript looks too short.
- Treating synthesis as ground truth instead of a map. Always drill to the
  per-source `_Insights.md` and its receipt file for load-bearing claims.
- Inconsistent `--topic` names across runs splits the corpus. Pick one slug
  and stick to it for a research area.
- Ignoring cost mode. Use `DISTILL_COST_MODE=no-metered` (or `--cost-mode`) to
  require implemented local Ollama or LM Studio inference and fail closed on
  API-billed or ambiguous routes. Direct plan-quota CLI adapters are not live
  Distill providers yet. An active-session worker is recorded as host-managed,
  not proven no-metered.
- Mistaking local inference for offline research. Ollama and LM Studio analyze
  fetched receipts locally, but discovery and ingest still fetch current public
  sources.
- Prompting the agent to "summarize the insights" without receipts. Force the
  agent to cite specific files and quote or reference the receipt content.
- Adding scratch notes beside a worker result. Worker submission accepts only
  `prompt.md`, `task.json`, and the new `result.md`; extra files fail closed.
- Leaving a failed worker claim stranded. Use `distill worker abandon` so a
  different host can claim it. Release an expired claim only after checking the
  original worker is no longer active.
