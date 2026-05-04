"""Papers ingestor — arXiv search and PDF extraction."""

from distill.ingestors.papers.arxiv import (
    ARXIV_API,
    PaperRecord,
    build_paper_document,
    fetch_arxiv_paper,
    fetch_paper_pdf_text,
    parse_arxiv_id,
    search_arxiv_multi,
    search_arxiv_papers,
)

__all__ = [
    "ARXIV_API",
    "PaperRecord",
    "build_paper_document",
    "fetch_arxiv_paper",
    "fetch_paper_pdf_text",
    "parse_arxiv_id",
    "search_arxiv_multi",
    "search_arxiv_papers",
]
