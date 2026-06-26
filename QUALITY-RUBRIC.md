# Quality Rubric

The self-review bar every change clears before commit. This file does not invent
standards; it operationalizes the canonical ones so review is repeatable:

- [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) - the CI gate and tool stack.
- [`docs/design/agentic-balance.md`](docs/design/agentic-balance.md) - rule-owned
  vs model-owned decisions (invariant #6/#8).
- [`docs/design/model-judgment-vs-brittle-fallbacks.md`](docs/design/model-judgment-vs-brittle-fallbacks.md)
  - the no-brittle-junk charter.
- [`ROADMAP.md`](ROADMAP.md) - the "No brittle junk" header and the 1.0 quality bar.

A change ships only when every category is 5/5. Below 5, fix before commit.

## Categories (1-5)

1. **Correctness.** Does what it claims; edge cases and failure modes handled;
   no behavior change unless intended and tested. 5 = covered by a focused test
   or a clear argument plus the existing suite; degrades cleanly on bad input.
2. **Security / trust boundary.** Ingested content is untrusted; paths are
   confined; secrets never logged; no SSRF/traversal/injection opened. 5 = the
   boundary is parsed once into a safe type and the unsafe state is
   unrepresentable downstream.
3. **Performance.** No needless work in hot/loop paths; context budget respected
   for prompts and MCP payloads (paths/previews over full bodies). 5 = the cost
   is justified and, where it changed, measured.
4. **Readability.** Reads like the surrounding code: same idiom, naming, comment
   density. 5 = a new contributor understands it without the author present;
   comments explain *why*, not *what*.
5. **Maintainability.** Small surface, single responsibility, honest types at
   boundaries, versioned durable contracts. 5 = illegal states unrepresentable;
   no silent error swallowing; the change localizes future edits.
6. **Simplicity / altitude (no brittle junk).** The decision sits at the right
   altitude: structural/ground-truth checks stay deterministic; quality /
   faithfulness / relevance judgments go to a model, never a keyword/length/
   cosine/threshold proxy. 5 = no deterministic scorer impersonates a semantic
   judgment, and no model is used where a structural check is correct.

## Gate (must all pass locally before push; CI re-validates)

- `uv run pyright <changed strict modules>` and `uv run pyright distill/llm/` - 0 errors.
- `uv run ruff check .` and `uv run ruff format --check .` - clean.
- `uv run bandit -r distill/ -c pyproject.toml --severity-level medium` - exit 0.
- `uv run lint-imports` - 4/4 contracts kept.
- `uv run pytest -q --cov=distill --cov-fail-under=89` - green, branch floor holds (up-only).
- Spend: $0 external by default (local validation); lifetime external <= $5.
