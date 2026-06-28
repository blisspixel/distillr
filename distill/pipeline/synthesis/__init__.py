# pyright: strict
"""Synthesis pipeline - cross-source synthesis orchestration."""

from distill.pipeline.synthesis.corpus import synthesize_corpus
from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

__all__ = [
    "synthesize_channel",
    "synthesize_corpus",
    "synthesize_topic",
]
