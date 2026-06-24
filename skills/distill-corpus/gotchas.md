# Gotchas (from real failure modes)

- Forgetting `--preview` before ingest or `distill discover` leads to surprise
  spend. Always preview and read the cost estimate.
- Stale syntheses or prompt versions produce confident but outdated prose.
  Run `distill audit <topic>` regularly; re-analyze or re-synthesize when
  flagged.
- Thin transcripts on long videos. The audit reports duration vs transcript
  length; do not trust analysis of videos where the transcript looks too short.
- Treating synthesis as ground truth instead of a map. Always drill to the
  per-source `_Insights.md` + its receipt file for load-bearing claims.
- Inconsistent `--topic` names across runs splits the corpus. Pick one slug
  and stick to it for a research area.
- Ignoring cost mode. Use `DISTILL_COST_MODE=no-metered` (or `--cost-mode`) when
  the operator has local or plan-quota routes; otherwise metered routes can
  activate silently.
- Prompting the agent to "summarize the insights" without receipts. Force the
  agent to cite specific files and quote or reference the receipt content.
