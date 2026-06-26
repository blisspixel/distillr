"""Prompts subpackage — all LLM prompt templates, organized by domain."""

# pyright: strict

from distill.prompts.analysis import *  # noqa: F403
from distill.prompts.analysis import __all__ as _analysis_all
from distill.prompts.discover import *  # noqa: F403
from distill.prompts.discover import __all__ as _discover_all
from distill.prompts.report import *  # noqa: F403
from distill.prompts.report import __all__ as _report_all
from distill.prompts.shared import *  # noqa: F403
from distill.prompts.shared import __all__ as _shared_all
from distill.prompts.synthesis import *  # noqa: F403
from distill.prompts.synthesis import __all__ as _synthesis_all

# The spread of each submodule's own (typed list[str]) __all__ resolves at
# runtime; pyright cannot statically verify a spread __all__, but the re-exported
# names are real, hence the targeted ignore.
__all__: list[str] = [  # pyright: ignore[reportUnsupportedDunderAll]
    *_analysis_all,
    *_discover_all,
    *_report_all,
    *_shared_all,
    *_synthesis_all,
]
