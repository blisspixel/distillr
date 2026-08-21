# pyright: strict
"""Cross-platform clean-install, cold-start, and export evidence."""

from benchmarks.user_experience.evidence import (
    BUNDLE_SCHEMA_VERSION,
    RunIdentity,
    build_evidence_bundle,
)
from benchmarks.user_experience.runner import (
    DEFAULT_ITERATIONS,
    EXPORT_SCALE,
    OPERATION_NAMES,
    RESULT_SCHEMA_VERSION,
    run_user_experience,
)

__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "DEFAULT_ITERATIONS",
    "EXPORT_SCALE",
    "OPERATION_NAMES",
    "RESULT_SCHEMA_VERSION",
    "RunIdentity",
    "build_evidence_bundle",
    "run_user_experience",
]
