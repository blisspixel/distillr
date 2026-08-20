# pyright: strict
"""Frozen receipts for offline workflow replay.

These are synthetic Distill receipts, not live fetches. Numeric claims in the
canned model bodies are grounded in the source text so verification stays clean.
"""

from __future__ import annotations

import hashlib
import json

from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.sites.scraper import SitePage

TOPIC = "replay-topic"
PAPER_ID = "2602.12670v1"
PAPER_TITLE = "Replay Memory for Agents"
VIDEO_TITLE = "Warm corpus scan"
SITE_TITLE = "Coverage note"
CHANNEL = "replay-channel"
VIDEO_ID = "dQwReplay000"
SITE_URL = "https://example.test/coverage"
REPLAY_MODEL = "replay-stub"

PAPER_ABSTRACT = (
    "We report MRR 72.6 on the frozen split and show that a Zettelkasten-style "
    "note graph stays under 16,900 tokens per memory operation."
)
PAPER_PDF_TEXT = """# Replay Memory for Agents

## Abstract

We report MRR 72.6 on the frozen split and show that a Zettelkasten-style
note graph stays under 16,900 tokens per memory operation.

## Methods

Evaluation uses a frozen 1,000-query split. Mean reciprocal rank is 72.6.
Token use per memory write is 1,200 versus 16,900 for the full-history baseline.

## Results

MRR 72.6 holds across three seeds. Retrieval latency is 14.22 ms on a warm
index of 1,000 notes.
"""
PAPER_INSIGHT_BODY = (
    "The paper reports MRR of 72.6 on the frozen split and 1,200 tokens per "
    "memory write versus 16,900 for the full-history baseline."
)

VIDEO_TRANSCRIPT = (
    "Today we timed a warm corpus scan. The scan finished in 14.22 ms on the "
    "warm index of 1,000 notes. Peak RSS stayed under 61 MiB."
)
VIDEO_INSIGHT_BODY = (
    "The scan finished in 14.22 ms on the warm index of 1,000 notes with peak RSS under 61 MiB."
)

SITE_TEXT = (
    "Branch coverage stayed at 95.04 percent across 6,582 tests. The floor remains 95 percent."
)
SITE_INSIGHT_BODY = (
    "Branch coverage stayed at 95.04 percent across 6,582 tests. The floor remains 95 percent."
)

SYNTHESIS_BODY = (
    "Across paper, video, and site receipts the replay corpus reports MRR 72.6, "
    "a 14.22 ms warm scan, and 95.04 percent branch coverage."
)

VERIFY_INSIGHT = "Grounded claims: MRR 72.6, 14.22 ms warm scan, and 95.04 percent coverage."
VERIFY_SOURCE = PAPER_PDF_TEXT + "\n" + VIDEO_TRANSCRIPT + "\n" + SITE_TEXT


def paper_record() -> PaperRecord:
    return PaperRecord(
        paper_id=PAPER_ID,
        title=PAPER_TITLE,
        abstract=PAPER_ABSTRACT,
        authors=["Ada Replay", "Bea Fixture"],
        abs_url=f"https://arxiv.org/abs/{PAPER_ID}",
        pdf_url=f"https://arxiv.org/pdf/{PAPER_ID}",
        published_at="2026-02-12",
    )


def site_page() -> SitePage:
    return SitePage(
        url=SITE_URL,
        title=SITE_TITLE,
        site_name="example.test",
        page_type="article",
        text=SITE_TEXT,
        final_url=SITE_URL,
        canonical_url=SITE_URL,
    )


def fixture_digest() -> str:
    payload = json.dumps(
        {
            "paper_abstract": PAPER_ABSTRACT,
            "paper_pdf": PAPER_PDF_TEXT,
            "paper_insight": PAPER_INSIGHT_BODY,
            "video_transcript": VIDEO_TRANSCRIPT,
            "video_insight": VIDEO_INSIGHT_BODY,
            "site_text": SITE_TEXT,
            "site_insight": SITE_INSIGHT_BODY,
            "synthesis": SYNTHESIS_BODY,
            "verify_insight": VERIFY_INSIGHT,
            "verify_source": VERIFY_SOURCE,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
