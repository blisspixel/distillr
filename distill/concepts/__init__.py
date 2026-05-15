"""Per-topic concept and entity playbooks.

The concept playbook layer accumulates evidence about named techniques,
architectures, datasets, metrics, people, organizations, and vendors across
the per-source ``_Insights.md`` files for a topic. It is the "21st paper
strengthens what the corpus knows" layer that turns distillr from a batch
processor into a living knowledge base.

Architecture (data flow):

    per-insight extraction (LLM)
            v
    mention records (JSONL, append-only)
            v
    deterministic merge (pure Python)
            v
    concept / entity playbook .md notes
            v
    contradiction surfacing + jsonl exports

Extraction is the only LLM step. Merge / normalize / render are pure Python:
commutative under source ordering, idempotent under repeated application,
property-tested in ``tests/unit/concepts/``.

Module surface:

- ``records`` -- dataclasses (``ConceptMention``, ``EvidenceInterval``,
  ``MergedConcept``) and the ``Polarity`` enum.
- ``normalize`` -- group mentions by canonical name, apply the source-count
  threshold filter.
- ``merge`` -- build evidence intervals and contested flag from grouped
  mentions. Pure; no IO, no LLM.
- ``notes`` -- render the playbook ``.md`` file from a ``MergedConcept``;
  manage ``.history/`` snapshots on overwrite.
- ``exports`` -- write per-topic ``concepts.jsonl`` and ``entities.jsonl``.
- ``extract`` -- LLM-driven extraction of mentions from one insight file.
- ``contradictions`` -- detect contested concepts for ``distill health``.
- ``pipeline`` -- ``run_concepts(topic, ...)`` end-to-end orchestrator.
"""

from __future__ import annotations

from distill.concepts.records import (
    ConceptKind,
    ConceptMention,
    EvidenceInterval,
    MergedConcept,
    Polarity,
    SourceEvidence,
)

__all__ = [
    "ConceptKind",
    "ConceptMention",
    "EvidenceInterval",
    "MergedConcept",
    "Polarity",
    "SourceEvidence",
]
