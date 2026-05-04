"""Backward-compatible re-exports. Import from distill.pipeline.discovery instead."""

import sys

import distill.pipeline.discovery as _canonical

sys.modules[__name__] = _canonical
