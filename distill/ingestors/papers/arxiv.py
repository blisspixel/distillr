"""arXiv-first paper discovery and ingestion helpers.

NOTE: arXiv enforces a rate limit of ~1 request per 3 seconds. Exceeding this
results in HTTP 429 responses. The networking layer handles generic retries, but
arXiv-specific callers add longer waits (30s) on 429 since arXiv's cooldown is
more aggressive than typical APIs.
"""

from __future__ import annotations

import logging
import re
import tempfile
import time
import urllib.parse
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from defusedxml.ElementTree import fromstring as xml_fromstring

from distill.ingestors.local.extract import extract_pdf_text_bounded
from distill.ingestors.net import NetworkError, safe_urlopen
from distill.parsing import parse_ascii_uint

logger = logging.getLogger(__name__)

__all__ = [
    "ARXIV_API",
    "PaperRecord",
    "build_paper_document",
    "fetch_arxiv_paper",
    "fetch_paper_pdf_text",
    "parse_arxiv_id",
    "search_arxiv",
    "search_arxiv_multi",
    "search_arxiv_papers",
]

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_PDF_PAGE_LIMIT = 200
_PDF_TEXT_LIMIT = 2_000_000
_PDF_DOWNLOAD_CAP_BYTES = 50 * 1024 * 1024
_PDF_MAX_REDIRECTS = 5
# Cap the Atom feed read, mirroring the PDF cap, so a compromised endpoint or a
# MITM cannot drive an unbounded read into memory at parse time.
_FEED_CAP_BYTES = 5 * 1024 * 1024
_ARXIV_REQUEST_SPACING_SECONDS = 3.5
_ARXIV_PDF_HOSTS = frozenset({"arxiv.org", "www.arxiv.org"})


@dataclass
class PaperRecord:
    paper_id: str
    title: str
    abstract: str
    authors: list[str] = field(default_factory=list)
    published_at: str = ""
    updated_at: str = ""
    categories: list[str] = field(default_factory=list)
    doi: str = ""
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
            "doi": self.doi,
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

    Includes a single arXiv-specific retry with a 30s wait on HTTP 429, since
    arXiv's rate-limit cooldown is longer than the generic backoff handles.
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
    try:
        return _parse_arxiv_feed(_fetch_text(url))
    except NetworkError as exc:
        if exc.status_code == 429:
            logger.warning("arXiv rate-limited. Waiting 30s before retry...")
            time.sleep(30)
            return _parse_arxiv_feed(_fetch_text(url))
        raise


def search_arxiv(query: str, max_results: int = 10) -> list[PaperRecord]:
    """Backward-compatible arXiv search alias used by MCP tools."""
    return search_arxiv_papers(query, limit=max_results)


def search_arxiv_multi(
    queries: list[str], limit_per_query: int = 10, *, sort: str = "relevance"
) -> list[PaperRecord]:
    """Run multiple arXiv searches, dedupe by paper_id, preserve first-seen order.

    Requests are spaced to respect arXiv's rate limit. If a 429 is encountered,
    the spacing increases adaptively. A transient error from any single query is
    swallowed so the batch can continue; callers can inspect the returned list
    size to decide whether to warn.
    """
    if not queries:
        return []
    seen: set[str] = set()
    combined: list[PaperRecord] = []
    spacing = _ARXIV_REQUEST_SPACING_SECONDS
    consecutive_failures = 0

    for idx, q in enumerate(queries):
        if idx:
            time.sleep(spacing)
        try:
            records = search_arxiv_papers(q, limit=limit_per_query, sort=sort)
            consecutive_failures = 0  # Reset on success
        except Exception:
            consecutive_failures += 1
            # Adaptive backoff: if we're getting rate-limited, wait longer
            if consecutive_failures >= 2:
                spacing = min(spacing * 2, 60.0)  # Double spacing, cap at 60s
                logger.warning(
                    "arXiv rate-limited. Waiting %.0fs before retry...",
                    spacing,
                )
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
        f"- DOI: {paper.doi or 'Unknown'}",
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

    Capped by page, text, memory, time, and download-size limits. Analysis chunks
    long documents when the provider window requires it. Returns empty on any
    network or parse failure; the pipeline falls back to abstract-only.
    """
    if not pdf_url:
        return ""
    try:
        data = _download_arxiv_pdf_bytes(pdf_url)
        if not data:
            return ""
        with tempfile.TemporaryDirectory(prefix="distill-arxiv-pdf-") as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(data)
            combined = extract_pdf_text_bounded(
                pdf_path,
                max_chars=_PDF_TEXT_LIMIT,
                max_pages=_PDF_PAGE_LIMIT,
            ).strip()
        # pypdf occasionally emits lone surrogate codepoints for supplementary-plane
        # characters (e.g. math alphanumerics). These break JSON encoding for the
        # API call. Roundtrip through utf-8 with errors='replace' to strip them.
        combined = combined.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        return combined
    except Exception:
        return ""


def _is_arxiv_pdf_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    # Accept http and https: arXiv's Atom feed serves pdf links as http://, and
    # rejecting those silently degraded extraction to abstract-only. The host
    # allow-list (not the scheme) is what bounds SSRF; http redirects to https.
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in _ARXIV_PDF_HOSTS
        and parsed.path.startswith("/pdf/")
    )


def _https_arxiv_url(url: str) -> str:
    """Upgrade an allow-listed arXiv ``http://`` URL to ``https://``.

    arXiv's Atom feed serves pdf links (and some redirect ``Location`` headers)
    as ``http://``. ``requests`` does not enforce HSTS, so fetching that URL as
    written makes a cleartext first hop an on-path attacker could intercept and
    answer with arbitrary PDF bytes (which then feed analysis/the corpus). The
    host allow-list bounds SSRF; forcing https before the request bounds that
    transport tampering. Leaves non-http schemes untouched.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "http":
        return parsed._replace(scheme="https").geturl()
    return url


def _download_arxiv_pdf_bytes(pdf_url: str) -> bytes:
    current_url = pdf_url
    for _ in range(_PDF_MAX_REDIRECTS + 1):
        if not _is_arxiv_pdf_url(current_url):
            return b""
        # Never fetch arXiv PDFs over cleartext: upgrade http -> https before the
        # request and on every redirect hop. The validator accepts http so a
        # feed-provided http link still routes here, but the wire is always TLS.
        current_url = _https_arxiv_url(current_url)
        with requests.get(
            current_url,
            timeout=60,
            stream=True,
            allow_redirects=False,
        ) as response:
            if 300 <= response.status_code < 400:
                location = response.headers.get("Location")
                if not location:
                    return b""
                current_url = urllib.parse.urljoin(current_url, location)
                continue
            response.raise_for_status()
            declared = response.headers.get("Content-Length")
            declared_size = parse_ascii_uint(declared or "")
            if declared_size is not None and declared_size > _PDF_DOWNLOAD_CAP_BYTES:
                return b""
            buf = BytesIO()
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _PDF_DOWNLOAD_CAP_BYTES:
                    return b""
                buf.write(chunk)
            return buf.getvalue()
    return b""


def _fetch_text(url: str) -> str:
    try:
        with safe_urlopen(url) as response:
            data = response.read(_FEED_CAP_BYTES + 1)
    except NetworkError as exc:
        raise NetworkError(
            f"arXiv request failed ({exc}). arXiv enforces a 3-second rate limit; "
            f"if you're seeing 429 errors, space requests further apart.",
            url=exc.url,
            status_code=exc.status_code,
        ) from exc
    if len(data) > _FEED_CAP_BYTES:
        raise NetworkError(f"arXiv response exceeds the {_FEED_CAP_BYTES:,}-byte cap.", url=url)
    return data.decode("utf-8", errors="replace")


def _parse_arxiv_feed(payload: str) -> list[PaperRecord]:
    try:
        root = xml_fromstring(payload)
    except Exception as exc:  # defusedxml raises several parse/defense errors
        # arXiv returns an HTML error page on some bad/rate-limited requests;
        # a non-XML body must degrade to "no results", not abort the run.
        logger.warning("arXiv feed is not parseable XML; treating as no results: %s", exc)
        return []
    results: list[PaperRecord] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        entry_id = _entry_text(entry, "atom:id").split("/")[-1]
        title = _clean_space(_entry_text(entry, "atom:title"))
        # Skip malformed/error entries (e.g. arXiv's API error feed) that carry no
        # real paper id or title; without this they become ghost records with an
        # empty paper_id, which collide on slug and contaminate the corpus.
        if not entry_id or not title:
            continue
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
                doi=_clean_space(_entry_text(entry, "arxiv:doi")),
                abs_url=abs_url,
                pdf_url=pdf_url,
            )
        )
    return results


def _entry_text(entry: Any, path: str) -> str:
    return entry.findtext(path, default="", namespaces=ATOM_NS)


def _clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
