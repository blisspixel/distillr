"""Library subpackage — filesystem corpus layer (foundational).

Provides artifact path resolution, state management, and export utilities.
"""

from distill.library.paths import *  # noqa: F403
from distill.library.paths import __all__ as _paths_all
from distill.library.state import (
    ChannelInfo,
    ChannelState,
    Library,
    TopicWatchEntry,
    WatchEntry,
)

__all__: list[str] = [
    *_paths_all,
    "ChannelInfo",
    "ChannelState",
    "Library",
    "TopicWatchEntry",
    "WatchEntry",
]
