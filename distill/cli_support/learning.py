"""Backward-compatible re-exports. Import from distill.commands._learning instead."""

import sys

import distill.commands._learning as _canonical

sys.modules[__name__] = _canonical
