"""Prompts subpackage — all LLM prompt templates, organized by domain."""

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

__all__: list[str] = [
    *_analysis_all,
    *_discover_all,
    *_report_all,
    *_shared_all,
    *_synthesis_all,
]
