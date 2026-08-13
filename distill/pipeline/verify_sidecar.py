"""Compatibility imports for the library-owned verification-sidecar contract."""

# pyright: strict

from distill.library.verify_sidecar import (
    VERIFY_SCHEMA_VERSION,
    EntailmentStatus,
    ParsedVerifyFlag,
    ParsedVerifySidecar,
    parse_verify_sidecar,
)

__all__ = [
    "VERIFY_SCHEMA_VERSION",
    "EntailmentStatus",
    "ParsedVerifyFlag",
    "ParsedVerifySidecar",
    "parse_verify_sidecar",
]
