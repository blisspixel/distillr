"""arXiv-first paper discovery and ingestion helpers."""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from xml.etree.ElementTree import Element  # Element is a type, not a parser

import requests
from defusedxml.ElementTree import fromstring as xml_fromstring
from pypdf import PdfReader

from distill.net import safe_urlopen

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_PDF_TEXT_LIMIT = 100_000
_PDF_PAGE_LIMIT = 40
_ARXIV_REQUEST_SPACING_SECONDS = 3.5


@dataclass
class PaperRecord:
    paper_id: str
    title: str
    abstract: str
    authors: list[str] = field(default_factory=list)
    published_at: str = ""
    updated_at: str = ""
    categories: list[str] = field(default_factory=list)
    abs_url: str = ""
    pdf_url: str = ""
    source: str = "arxiv"

    def metadata(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "published_at": self.published_at,
            "updated_at": self.updated_at,
            "categories": self.categories,
            "abs_url": self.abs_url,
            "pdf_url": self.pdf_url,
            "source": self.source,
        }


def parse_arxiv_id(value: str) -> str:
    text = value.strip()
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", text, re.IGNORECASE)
    paper_id = match.group(1) if match else text
    paper_id = paper_id.removesuffix(".pdf")
    return paper_id.strip()


def search_arxiv_papers(query: str, limit: int = 10, *, sort: str = "date") -> list[PaperRecord]:
    """Search arXiv for papers matching a query.

    sort: "date" (newest first, arXiv default behavior) or "relevance"
    (arXiv's own relevance ranking via sortBy=relevance).
    """
    sort_by = "relevance" if sort == "relevance" else "submittedDate"
    params = {
        "search_query": _build_search_query(query),
        "start": "0",
        "max_results": str(limit),
        "sortBy": sort_by,
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    return _parse_arxiv_feed(_fetch_text(url))


def search_arxiv_multi(
    queries: list[str], limit_per_query: int = 10, *, sort: str = "relevance"
) -> list[PaperRecord]:
    """Run multiple arXiv searches, dedupe by paper_id, preserve first-seen order.

    Requests are spaced to respect arXiv's rate limit (3s minimum; we use 3.5s).
    A 429 or transient error from any single query is swallowed so the batch can
    continue; failures are silent here -- callers can inspect the returned list
    size to decide whether to warn. Use this when an upstream caller has already
    expanded a user query into variants; do not call this in a tight loop.
    """
    if not queries:
        return []
    seen: set[str] = set()
    combined: list[PaperRecord] = []
    for idx, q in enumerate(queries):
        if idx:
            time.sleep(_ARXIV_REQUEST_SPACING_SECONDS)
        try:
            records = search_arxiv_papers(q, limit=limit_per_query, sort=sort)
        except Exception:
            continue
        for record in records:
            if record.paper_id in seen:
                continue
            seen.add(record.paper_id)
            combined.append(record)
    return combined


def _build_search_query(query: str) -> str:
    """Build an arXiv search expression that's tight without being too strict.

    arXiv parses bare multi-term input as OR, which floods results with noise
    (three OR'd tokens like `temporal knowledge graph` return any paper mentioning
    any of those words). The previous fix wrapped multi-word queries in quotes
    for strict phrase-match, but that is too strict for 3+ word LLM-generated
    queries: "symbolic music transformer composition" as a literal phrase returns
    zero.

    Current policy:
    - Empty -> "all:".
    - Pre-operator input (contains quotes, AND/OR, or parens) -> pass through.
    - 1 word -> single-term search.
    - 2 words -> phrase match ("music transformer", "agent memory" are naturally
      phrasal, and phrase match keeps precision high).
    - 3+ words -> AND-joined tokens, so every term must appear but not necessarily
      adjacent. This is the sweet spot between OR-noise and phrase-brittleness.
    Callers who need custom AND/OR/grouping can pass a pre-quoted or operator
    query and the quoting is skipped.
    """
    stripped = query.strip()
    if not stripped:
        return "all:"
    if any(token in stripped for token in ('"', " AND ", " OR ", "(")):
        return f"all:{stripped}"
    words = stripped.split()
    if len(words) == 1:
        return f"all:{stripped}"
    if len(words) == 2:
        return f'all:"{stripped}"'
    return " AND ".join(f"all:{w}" for w in words)


def fetch_arxiv_paper(url_or_id: str) -> PaperRecord | None:
    paper_id = parse_arxiv_id(url_or_id)
    params = {"id_list": paper_id}
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    records = _parse_arxiv_feed(_fetch_text(url))
    return records[0] if records else None


def build_paper_document(paper: PaperRecord, pdf_text: str = "") -> str:
    authors = ", ".join(paper.authors) if paper.authors else "Unknown"
    categories = ", ".join(paper.categories) if paper.categories else "Unknown"
    lines = [
        f"# {paper.title}",
        "",
        f"- Paper ID: `{paper.paper_id}`",
        f"- Authors: {authors}",
        f"- Published: {paper.published_at or 'Unknown'}",
        f"- Updated: {paper.updated_at or 'Unknown'}",
        f"- Categories: {categories}",
        f"- Abstract URL: {paper.abs_url or 'Unknown'}",
        f"- PDF URL: {paper.pdf_url or 'Unknown'}",
        "",
        "## Abstract",
        "",
        paper.abstract.strip(),
        "",
    ]
    if pdf_text:
        lines.extend(["## Full Paper Text", "", pdf_text.strip(), ""])
    return "\n".join(lines)


def fetch_paper_pdf_text(pdf_url: str) -> str:
    """Download an arXiv PDF and return extracted text, or empty string on failure.

    Capped at _PDF_PAGE_LIMIT pages and _PDF_TEXT_LIMIT chars to keep per-paper
    analysis cost predictable. Returns empty on any network or parse failure;
    the analysis pipeline falls back to abstract-only in that case.
    """
    if not pdf_url:
        return ""
    try:
        response = requests.get(pdf_url, timeout=60)
        response.raise_for_status()
        reader = PdfReader(BytesIO(response.content))
        text_parts: list[str] = []
        for page in reader.pages[:_PDF_PAGE_LIMIT]:
            text = (page.extract_text() or "").strip()
            if text:
                text_parts.append(text)
        combined = "\n\n".join(text_parts).strip()
        # pypdf occasionally emits lone surrogate codepoints for supplementary-plane
        # characters (e.g. math alphanumerics). These break JSON encoding for the
        # API call. Roundtrip through utf-8 with errors='replace' to strip them.
        combined = combined.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        return combined[:_PDF_TEXT_LIMIT]
    except Exception:
        return ""


def _fetch_text(url: str) -> str:
    with safe_urlopen(url) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_arxiv_feed(payload: str) -> list[PaperRecord]:
    root = xml_fromstring(payload)
    results: list[PaperRecord] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        entry_id = _entry_text(entry, "atom:id").split("/")[-1]
        title = _clean_space(_entry_text(entry, "atom:title"))
        abstract = _clean_space(_entry_text(entry, "atom:summary"))
        authors = [
            _clean_space(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
            if _clean_space(author.findtext("atom:name", default="", namespaces=ATOM_NS))
        ]
        categories = [
            item.attrib.get("term", "") for item in entry.findall("atom:category", ATOM_NS)
        ]
        abs_url = ""
        pdf_url = ""
        for link in entry.findall("atom:link", ATOM_NS):
            href = link.attrib.get("href", "")
            title_attr = link.attrib.get("title", "")
            if title_attr == "pdf":
                pdf_url = href
            elif link.attrib.get("rel") == "alternate" and href:
                abs_url = href
        results.append(
            PaperRecord(
                paper_id=entry_id,
                title=title,
                abstract=abstract,
                authors=authors,
                published_at=_entry_text(entry, "atom:published"),
                updated_at=_entry_text(entry, "atom:updated"),
                categories=[c for c in categories if c],
                abs_url=abs_url,
                pdf_url=pdf_url,
            )
        )
    return results


def _entry_text(entry: Element, path: str) -> str:
    return entry.findtext(path, default="", namespaces=ATOM_NS)


def _clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
