"""Write-time claim grounding -- the deterministic first cut of the verify hook.

Anthropic's agent loop is gather -> act -> *verify*; distill gathers (discover)
and acts (analyze + synthesize), and this module is the verify leg at write
time: before an ``_Insights.md`` is committed to the library, its load-bearing
numeric claims are checked against the source receipt sitting in the same
directory, and the result lands in a ``_Verify.json`` sidecar.

Scope of this tier is deliberate (the dogfood corpus in
``library/topics/claim-verification/`` settled the design):

- **Numbers, percents, money, and years only.** These are the highest-precision
  claim class to check deterministically, and the measured hard class when
  hallucinated (QuanTemp: conflicting numerical claims peak at 47.33 F1).
  Named entities defer to the small-local-entailment-checker tier, which layers
  on top of this one and never replaces it.
- **Pure string/arithmetic checking.** Per the invariants: LLM proposes, Python
  decides -- no LLM-as-judge-of-record. A number the analysis model wrote that
  does not appear in (or round from) the source text is flagged, full stop.
- A flag means "support not found", not "false": the sidecar carries the
  context line so a human or the audit surface can adjudicate.

Modes (``DISTILL_VERIFY`` or ``--verify`` on the ingest commands): ``warn``
(default -- flag to console, write anyway), ``strict`` (refuse to write an
insight with unsupported claims; the sidecar still records why), ``off``
(skip the check).
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from distill.library.paths import artifact_path, atomic_write_text, strip_frontmatter
from distill.pipeline.verify_entailment import (
    EntailmentChecker,
    EntailmentReport,
    evaluate_entailment,
    load_default_checker,
)

__all__ = [
    "NumericClaim",
    "VerifyOutcome",
    "VerifyReport",
    "extract_numeric_claims",
    "resolve_verify_mode",
    "run_synthesis_verify",
    "run_verify_hook",
    "verify_insight",
    "write_verify_sidecar",
]

# v2 adds the additive "entailment" block (0.13.0); v1 sidecars stay valid and
# readers treat a missing block as "entailment not run".
VERIFY_SCHEMA_VERSION = 2

# The entailment checker loads once per process (the model is ~110M params);
# None-after-attempt means the optional extra is absent and the deterministic
# tier stands alone, exactly as before the tier existed.
_checker_loaded = False
_checker: EntailmentChecker | None = None


def _entailment_checker() -> EntailmentChecker | None:
    global _checker_loaded, _checker
    if not _checker_loaded:
        _checker = load_default_checker()
        _checker_loaded = True
    return _checker


# Claim-side token shapes, most specific first. Small bare integers (<= 3
# digits, no decimal/percent/currency) are deliberately not claims: list
# numbers, rankings, and "3 methods" would drown the signal.
_CLAIM_TOKEN_RE = re.compile(
    r"""
    (?<![\w.])
    (?:
        \$\d[\d,]*(?:\.\d+)?            # money: $200, $1,250.50
      | \d{1,3}(?:,\d{3})+(?:\.\d+)?%?  # separated integer: 15,514 / 1,000.5%
      | \d+\.\d+%?                      # decimal: 72.6 / 0.878 / 47.33%
      | \d+%                            # integer percent: 80%
      | (?:19|20)\d{2}                  # year: 1998, 2026
    )
    (?![\w%])(?!\.\d)                   # boundary: a sentence period is fine,
    """,  # a continued number/word is not
    re.VERBOSE,
)

# Unit-bearing small numbers are load-bearing in hardware and deployment
# research, even when the bare integer would be too noisy to check globally.
_UNIT_CLAIM_TOKEN_RE = re.compile(
    r"""
    (?<![\w.])
    (?P<num>\d+(?:\.\d+)?)
    \s*
    (?:
        [KMGTPE]?i?B(?:/s)?        # GB, GiB, TB/s
      | [KMGTPE]?B(?:/s)?          # MB, GB, TB, GB/s
      | GbE|Gb/s|Gbit/s
      | W|kW|MW
      | PFLOPS?|TFLOPS?|TOPS|FLOPS?
      | degrees?\s*[CF]
      | \N{DEGREE SIGN}[CF]
      | billion|million|trillion
      | [BMT]
      | parameters?
    )
    (?![\w%])
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Source-side tokens are broader: any digit run (plus comma/space-separated
# thousands) so a claim can match however the source typeset it. PDF extraction
# often renders 15,514 as "15 514".
_SOURCE_TOKEN_RE = re.compile(r"\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

# Insight tokens that look numeric but are identifiers, not claims.
_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")

# Strip these spans from insight lines before scanning: URLs and markdown link
# targets carry digits (arxiv.org/abs/2604.11544) that are not prose claims.
_URL_RE = re.compile(r"https?://\S+|\]\([^)]*\)")

_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class NumericClaim:
    """One load-bearing numeric token found in an insight body."""

    token: str  # as written: "72.6", "15,514", "47.33%", "$200", "2026"
    kind: str  # "money" | "integer" | "decimal" | "percent" | "year"
    context: str  # the (trimmed) line it appeared on


@dataclass(frozen=True)
class VerifyReport:
    """Outcome of grounding one insight against its source receipt."""

    checked: int
    unsupported: tuple[NumericClaim, ...]
    mode: str

    @property
    def supported(self) -> int:
        return self.checked - len(self.unsupported)

    @property
    def ok(self) -> bool:
        return not self.unsupported


def _classify(token: str) -> str:
    if token.startswith("$"):
        return "money"
    if token.endswith("%"):
        return "percent"
    if "." in token:
        return "decimal"
    if "," in token:
        return "integer"
    return "year" if re.fullmatch(r"(?:19|20)\d{2}", token) else "integer"


def _canonical(token: str) -> str:
    """Normalize a token to a bare digit string: ``$15,514.50%`` -> ``15514.50``."""
    return token.strip("$%").replace(",", "").replace(" ", "")


def extract_numeric_claims(insight_text: str) -> list[NumericClaim]:
    """Pull the checkable numeric claims out of an insight's markdown body.

    Frontmatter, fenced code blocks, URLs/markdown link targets, and
    arXiv-shaped identifiers are excluded; everything else that matches the
    claim shapes above is a claim the source must support.
    """
    body = strip_frontmatter(insight_text)
    claims: list[NumericClaim] = []
    in_fence = False
    for raw_line in body.splitlines():
        if _FENCE_RE.match(raw_line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = _URL_RE.sub(" ", raw_line)
        for match in _CLAIM_TOKEN_RE.finditer(line):
            token = match.group(0)
            if _ARXIV_ID_RE.fullmatch(_canonical(token)):
                continue
            claims.append(
                NumericClaim(token=token, kind=_classify(token), context=raw_line.strip())
            )
        covered_spans = [match.span() for match in _CLAIM_TOKEN_RE.finditer(line)]
        for match in _UNIT_CLAIM_TOKEN_RE.finditer(line):
            if any(start <= match.start("num") < end for start, end in covered_spans):
                continue
            token = match.group("num")
            if _ARXIV_ID_RE.fullmatch(_canonical(token)):
                continue
            claims.append(
                NumericClaim(token=token, kind=_classify(token), context=raw_line.strip())
            )
    return claims


def _source_values(source_text: str) -> tuple[set[str], list[float]]:
    """Every numeric token in the source, as canonical strings and as floats."""
    strings: set[str] = set()
    values: list[float] = []
    for match in _SOURCE_TOKEN_RE.finditer(source_text):
        canon = _canonical(match.group(0))
        if canon in strings:
            continue
        strings.add(canon)
        try:
            values.append(float(canon))
        except ValueError:  # pragma: no cover - canon is digits by construction
            continue
    return strings, values


def _is_supported(claim: NumericClaim, strings: set[str], values: list[float]) -> bool:
    canon = _canonical(claim.token)
    if canon in strings:
        return True
    # Rounding support: the model may legitimately round "0.878" to "0.88".
    # A claim with d decimals is supported by any source value within half a
    # unit in the last place. Integers/years get no tolerance: a year or count
    # that differs is wrong, not rounded.
    if "." not in canon:
        return False
    decimals = len(canon.split(".", 1)[1])
    try:
        target = float(canon)
    except ValueError:  # pragma: no cover - canon is digits by construction
        return False
    tolerance = 0.5 * (10**-decimals) + 1e-12
    return any(abs(value - target) <= tolerance for value in values)


def verify_insight(insight_text: str, source_text: str, *, mode: str = "warn") -> VerifyReport:
    """Ground every numeric claim in *insight_text* against *source_text*.

    Pure: no IO. Dedups identical tokens (one flag per distinct unsupported
    token, first context line wins) so a repeated number doesn't multi-count.
    """
    claims = extract_numeric_claims(insight_text)
    strings, values = _source_values(source_text)
    unsupported: list[NumericClaim] = []
    seen: set[str] = set()
    for claim in claims:
        canon = _canonical(claim.token)
        if canon in seen:
            continue
        if not _is_supported(claim, strings, values):
            seen.add(canon)
            unsupported.append(claim)
    return VerifyReport(checked=len(claims), unsupported=tuple(unsupported), mode=mode)


def resolve_verify_mode(raw: str) -> str:
    """Normalize the configured verify mode; unknown values degrade to ``warn``.

    A typo'd env var must not abort an ingest run (clean degradation), and
    quietly skipping verification would be worse than over-checking -- so the
    safe fallback is ``warn``.
    """
    mode = (raw or "").strip().lower()
    if mode in {"off", "strict"}:
        return mode
    return "warn"


@dataclass(frozen=True)
class VerifyOutcome:
    """A completed verification pass: the report, its sidecar, and what to do.

    ``refused`` is the strict-mode signal: the caller must not write the
    insight artifact (the sidecar still exists, recording exactly why).
    ``summary_line`` is the ready-made console message so every emit path
    flags identically.
    """

    report: VerifyReport
    sidecar: Path
    insight_name: str = ""
    entailment: EntailmentReport | None = None

    @property
    def _entailment_flags(self) -> int:
        return len(self.entailment.flagged) if self.entailment else 0

    @property
    def refused(self) -> bool:
        if self.report.mode != "strict":
            return False
        return not self.report.ok or self._entailment_flags > 0

    @property
    def summary_line(self) -> str:
        n, total = len(self.report.unsupported), self.report.checked
        ent = f" + {self._entailment_flags} prose claim(s)" if self._entailment_flags else ""
        if self.refused:
            name = self.insight_name or "insight"
            return (
                f"verify strict: refused {name} -- {n}/{total} unsupported "
                f"numeric claim(s){ent}; see {self.sidecar.name}"
            )
        return (
            f"verify: {n}/{total} numeric claim(s){ent} lack source support -- "
            f"see {self.sidecar.name}"
        )


def run_verify_hook(
    directory: Path,
    insight_text: str,
    source_text: str,
    *,
    mode: str,
    identity: str | None = None,
    insight_name: str = "",
    source_name: str = "",
) -> VerifyOutcome | None:
    """Verify one insight against its receipt and write the sidecar.

    The single entry point analysis emit paths call, *before* writing the
    insight artifact (strict mode must be able to refuse the write). Returns
    ``None`` when the mode is ``off`` or there is no source text to check
    against (nothing to ground means nothing to claim about grounding).
    Never raises on sidecar IO problems -- verification bookkeeping must not
    kill an ingest run -- but the outcome is still returned so callers can
    surface flags and honor refusal.
    """
    if mode == "off" or not source_text.strip():
        return None
    report = verify_insight(insight_text, source_text, mode=mode)
    entailment: EntailmentReport | None = None
    checker = _entailment_checker()
    if checker is not None:
        try:
            entailment = evaluate_entailment(insight_text, source_text, checker)
        except Exception:
            # The optional tier must never kill an ingest run; the
            # deterministic report stands and the sidecar records no block.
            entailment = None
    path = artifact_path(directory, "verify", identity=identity, extension="json")
    with contextlib.suppress(OSError):
        path = write_verify_sidecar(
            directory,
            report,
            identity=identity,
            insight_name=insight_name,
            source_name=source_name,
            entailment=entailment,
        )
    return VerifyOutcome(
        report=report, sidecar=path, insight_name=insight_name, entailment=entailment
    )


def run_synthesis_verify(
    directory: Path,
    synthesis: str,
    receipt: str,
    *,
    verify_mode: str,
    identity: str,
    insight_name: str,
    source_name: str,
    notify: Callable[[str], None],
) -> bool:
    """Verify a synthesis against its own inputs and report via *notify*.

    The shared tail every synthesis emit path runs (0.13.1): a synthesis is
    grounded against the receipt it was built from (per-source insights or the
    rendered claim set), the summary line is surfaced through *notify* (a
    ``console.print`` or ``logger.warning`` -- callers differ), and the return
    value is the strict-mode refusal signal: ``True`` means the caller must not
    write the artifact (the sidecar still records exactly why).
    """
    outcome = run_verify_hook(
        directory,
        synthesis,
        receipt,
        mode=resolve_verify_mode(verify_mode),
        identity=identity,
        insight_name=insight_name,
        source_name=source_name,
    )
    if outcome is None:
        return False
    if not outcome.report.ok:
        notify(outcome.summary_line)
    return outcome.refused


def write_verify_sidecar(
    directory: Path,
    report: VerifyReport,
    *,
    identity: str | None = None,
    insight_name: str = "",
    source_name: str = "",
    entailment: EntailmentReport | None = None,
) -> Path:
    """Write the ``<stem>_Verify.json`` sidecar next to the insight artifact."""
    path = artifact_path(directory, "verify", identity=identity, extension="json")
    payload = {
        "schema_version": VERIFY_SCHEMA_VERSION,
        "mode": report.mode,
        "checked": report.checked,
        "supported": report.supported,
        "unsupported": [
            {"token": c.token, "kind": c.kind, "context": c.context} for c in report.unsupported
        ],
        "insight": insight_name,
        "source": source_name,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if entailment is not None:
        payload["entailment"] = {
            "checked": entailment.checked,
            "supported": entailment.supported,
            "flagged": list(entailment.flagged),
            "model": entailment.model,
            "threshold": entailment.threshold,
        }
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")
    return path
