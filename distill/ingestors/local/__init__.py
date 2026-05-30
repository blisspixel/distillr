"""Local-file ingestion: extract analyzable text from on-disk documents."""

from distill.ingestors.local.extract import (
    LocalDocument,
    LocalExtractionError,
    extract_local_document,
)

__all__ = [
    "LocalDocument",
    "LocalExtractionError",
    "extract_local_document",
]
