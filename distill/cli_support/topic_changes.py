"""Backward-compatible re-exports. Import from distill.commands._topic_changes instead."""

import sys

import distill.commands._topic_changes as _canonical

sys.modules[__name__] = _canonical
