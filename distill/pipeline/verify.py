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
(skip the check). Saved-answer promotion additionally requires a complete,
clean semantic report and fails closed when the optional checker is absent or
fails.
"""

# pyright: strict

from __future__ import annotations

import contextlib
import json
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import deal

from distill.library.confined_state import (
    ConfinedStateError,
    FileIdentity,
    atomic_write_confined_bytes,
    confined_file_identity,
    confined_state_lock_path,
    ensure_confined_parent,
    read_confined_state_bytes,
    unlink_confined_file,
)
from distill.library.insights import insight_content_sha256
from distill.library.locking import exclusive_path_lock
from distill.library.paths import (
    artifact_path,
    atomic_write_text,
    render_markdown_artifact,
    strip_frontmatter,
    write_text_artifact,
)
from distill.pipeline.verify_entailment import (
    EntailmentChecker,
    EntailmentReport,
    evaluate_entailment,
    load_default_checker,
)
from distill.pipeline.verify_sidecar import VERIFY_SCHEMA_VERSION, EntailmentStatus

__all__ = [
    "EntailmentStatus",
    "NumericClaim",
    "VerifyOutcome",
    "VerifyReport",
    "entailment_checker_available",
    "extract_numeric_claims",
    "resolve_verify_mode",
    "run_synthesis_verify",
    "run_verify_hook",
    "verify_insight",
    "write_verified_artifact",
    "write_verified_synthesis",
    "write_verify_sidecar",
]

_MAX_VERIFY_SIDECAR_BYTES = 8 * 1024 * 1024

# The entailment checker loads once per process (the model is ~110M params);
# None-after-attempt means the optional extra is absent and the deterministic
# tier stands alone, exactly as before the tier existed.
_checker_loaded = False
_checker: EntailmentChecker | None = None
_checker_lock = threading.Lock()


def _entailment_checker() -> EntailmentChecker | None:
    global _checker_loaded, _checker
    if not _checker_loaded:
        with _checker_lock:
            if not _checker_loaded:
                _checker = load_default_checker()
                _checker_loaded = True
    return _checker


def entailment_checker_available() -> bool:
    """Return whether the pinned local semantic checker loaded successfully."""
    return _entailment_checker() is not None


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


_VALID_CLAIM_KINDS = frozenset({"money", "percent", "decimal", "integer", "year"})


def _claims_well_formed(claims: list[NumericClaim]) -> bool:
    """Every extracted claim has a non-empty token and a known kind.

    Runtime contract over extraction from untrusted markdown
    (docs/design/verification-depth.md): a regex or classifier change that ever
    emitted an empty token or an unknown kind is caught at the boundary.
    """
    return all(bool(c.token) and c.kind in _VALID_CLAIM_KINDS for c in claims)


@deal.post(_claims_well_formed)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
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
    insight artifact. Generic insight verification publishes the refusal
    sidecar; synthesis verification can defer publication so a rejected
    candidate cannot replace the sidecar bound to the prior artifact.
    ``summary_line`` is the ready-made console message so every emit path flags
    identically.
    """

    report: VerifyReport
    sidecar: Path
    insight_name: str = ""
    entailment: EntailmentReport | None = None
    entailment_status: EntailmentStatus = "not_required"
    entailment_required: bool = False
    entailment_reason: str = ""

    @property
    def _entailment_flags(self) -> int:
        return len(self.entailment.flagged) if self.entailment else 0

    @property
    def refused(self) -> bool:
        if self.report.mode != "strict":
            return False
        semantic_passed = (
            self.entailment_status == "passed"
            and self.entailment is not None
            and self.entailment.checked > 0
            and not self.entailment.flagged
        )
        semantic_refusal = self.entailment_required and not semantic_passed
        return not self.report.ok or self._entailment_flags > 0 or semantic_refusal

    @property
    def summary_line(self) -> str:
        n, total = len(self.report.unsupported), self.report.checked
        ent = f" + {self._entailment_flags} prose claim(s)" if self._entailment_flags else ""
        if self.refused:
            name = self.insight_name or "insight"
            semantic = ""
            if self.entailment_required and self.entailment_status != "passed":
                semantic = {
                    "unavailable": "; semantic checker unavailable",
                    "error": "; semantic checker failed",
                    "incomplete": "; semantic verification incomplete",
                    "flagged": "; semantic verification flagged unsupported prose",
                    "not_required": "; semantic verification did not run",
                }.get(self.entailment_status, "")
            return (
                f"verify strict: refused {name} -- {n}/{total} unsupported "
                f"numeric claim(s){ent}{semantic}; see {self.sidecar.name}"
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
    require_entailment: bool = False,
    insight_sha256: str | None = None,
    publish_sidecar: bool = True,
) -> VerifyOutcome | None:
    """Verify one insight against its receipt and optionally write the sidecar.

    The single entry point analysis emit paths call, *before* writing the
    insight artifact (strict mode must be able to refuse the write). Returns
    ``None`` when the mode is ``off`` or there is no source text to check
    against (nothing to ground means nothing to claim about grounding).
    When ``publish_sidecar`` is true, sidecar IO problems are suppressed so
    verification bookkeeping cannot kill an ingest run. The outcome is still
    returned so callers can surface flags and honor refusal. Synthesis callers
    set ``publish_sidecar`` false and publish the bound sidecar only after the
    candidate passes validation.
    """
    if mode == "off" or not source_text.strip():
        return None
    report = verify_insight(insight_text, source_text, mode=mode)
    entailment: EntailmentReport | None = None
    entailment_status: EntailmentStatus = "not_required"
    entailment_reason = ""
    checker = _entailment_checker()
    if checker is None:
        if require_entailment:
            entailment_status = "unavailable"
            entailment_reason = "checker unavailable"
    else:
        try:
            entailment = evaluate_entailment(insight_text, source_text, checker)
        except Exception:
            entailment = None
            if require_entailment:
                entailment_status = "error"
                entailment_reason = "checker evaluation failed"
        else:
            if entailment.checked == 0:
                entailment_status = "incomplete"
                entailment_reason = "no prose claims checked"
            elif entailment.flagged:
                entailment_status = "flagged"
            else:
                entailment_status = "passed"
    path = artifact_path(directory, "verify", identity=identity, extension="json")
    if publish_sidecar:
        with contextlib.suppress(OSError):
            path = write_verify_sidecar(
                directory,
                report,
                identity=identity,
                insight_name=insight_name,
                insight_sha256=insight_sha256,
                source_name=source_name,
                entailment=entailment,
                entailment_status=entailment_status,
                entailment_reason=entailment_reason,
            )
    return VerifyOutcome(
        report=report,
        sidecar=path,
        insight_name=insight_name,
        entailment=entailment,
        entailment_status=entailment_status,
        entailment_required=require_entailment,
        entailment_reason=entailment_reason,
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
    insight_sha256: str,
    notify: Callable[[str], None],
) -> bool:
    """Verify a synthesis against its own inputs and report via *notify*.

    The shared tail every synthesis emit path runs (0.13.1): a synthesis is
    grounded against the receipt it was built from (per-source insights or the
    rendered claim set), the summary line is surfaced through *notify* (a
    ``console.print`` or ``logger.warning`` -- callers differ), and the return
    value is the refusal signal: ``True`` means the caller must not write the
    artifact. A rejected strict candidate does not replace the sidecar bound to
    the prior artifact.
    """
    mode = resolve_verify_mode(verify_mode)
    sidecar = artifact_path(directory, "verify", identity=identity, extension="json")
    if mode == "off" or not receipt.strip():
        try:
            sidecar_identity = confined_file_identity(sidecar, directory)
            if sidecar_identity is not None:
                unlink_confined_file(sidecar, directory, expected=sidecar_identity)
        except (OSError, ConfinedStateError):
            notify(
                f"Synthesis not written because stale verification sidecar "
                f"{sidecar.name} could not be removed."
            )
            return True
        return False

    outcome = run_verify_hook(
        directory,
        synthesis,
        receipt,
        mode=mode,
        identity=identity,
        insight_name=insight_name,
        source_name=source_name,
        insight_sha256=insight_sha256,
        publish_sidecar=False,
    )
    if outcome is None:
        return True
    if outcome.refused:
        summary = outcome.summary_line.rsplit("; see ", 1)[0]
        notify(f"{summary}; previous artifact and verification sidecar retained")
        return True
    if not outcome.report.ok:
        notify(outcome.summary_line)
    try:
        write_verify_sidecar(
            directory,
            outcome.report,
            identity=identity,
            insight_name=insight_name,
            insight_sha256=insight_sha256,
            source_name=source_name,
            entailment=outcome.entailment,
            entailment_status=outcome.entailment_status,
            entailment_reason=outcome.entailment_reason,
        )
    except OSError:
        notify(
            f"Synthesis not written because verification sidecar {sidecar.name} "
            "could not be published."
        )
        return True
    return False


def write_verified_synthesis(
    directory: Path,
    artifact_type: str,
    synthesis: str,
    receipt: str,
    *,
    verify_mode: str,
    artifact_identity: str,
    verify_identity: str,
    source_name: str,
    notify: Callable[[str], None],
    frontmatter: Mapping[str, Any] | None = None,
) -> Path | None:
    """Verify and persist one exact rendered synthesis plus its bound sidecar."""

    rendered = render_markdown_artifact(
        artifact_type,
        synthesis,
        frontmatter=frontmatter,
    )
    output_path = artifact_path(directory, artifact_type, identity=artifact_identity)
    sidecar_path = artifact_path(
        directory,
        "verify",
        identity=verify_identity,
        extension="json",
    )

    def publish_sidecar() -> bool:
        return run_synthesis_verify(
            directory,
            synthesis,
            receipt,
            verify_mode=verify_mode,
            identity=verify_identity,
            insight_name=output_path.name,
            source_name=source_name,
            insight_sha256=insight_content_sha256(rendered),
            notify=notify,
        )

    return _publish_bound_artifact(
        directory,
        sidecar_path,
        publish_sidecar=publish_sidecar,
        publish_artifact=lambda: write_text_artifact(
            directory,
            artifact_type,
            rendered,
            identity=artifact_identity,
        ),
    )


def write_verified_artifact(
    directory: Path,
    output_path: Path,
    content: str,
    *,
    outcome: VerifyOutcome,
    verify_identity: str,
    source_name: str,
) -> Path:
    """Publish an already-verified artifact and its digest-bound sidecar."""

    sidecar_path = artifact_path(
        directory,
        "verify",
        identity=verify_identity,
        extension="json",
    )

    def publish_sidecar() -> bool:
        write_verify_sidecar(
            directory,
            outcome.report,
            identity=verify_identity,
            insight_name=output_path.name,
            insight_sha256=insight_content_sha256(content),
            source_name=source_name,
            entailment=outcome.entailment,
            entailment_status=outcome.entailment_status,
            entailment_reason=outcome.entailment_reason,
        )
        return False

    published = _publish_bound_artifact(
        directory,
        sidecar_path,
        publish_sidecar=publish_sidecar,
        publish_artifact=lambda: _write_verified_output(output_path, content),
    )
    if published is None:  # pragma: no cover - callback always publishes
        raise RuntimeError("Verified artifact publication was unexpectedly refused")
    return published


def _write_verified_output(path: Path, content: str) -> Path:
    atomic_write_text(path, content)
    return path


def _publish_bound_artifact(
    directory: Path,
    sidecar_path: Path,
    *,
    publish_sidecar: Callable[[], bool],
    publish_artifact: Callable[[], Path],
) -> Path | None:
    """Serialize and roll back one sidecar-first artifact publication."""

    directory.mkdir(parents=True, exist_ok=True)
    lock_path = confined_state_lock_path(
        directory / ".verification-bindings",
        directory,
        "verification",
    )
    ensure_confined_parent(lock_path, directory, create=False)
    with exclusive_path_lock(
        lock_path,
        timeout_seconds=30.0,
        timeout_message=f"Timed out publishing verified artifact in {directory}",
    ):
        prior_sidecar = _read_verification_sidecar_snapshot(sidecar_path, directory)
        if publish_sidecar():
            return None
        published_sidecar = confined_file_identity(sidecar_path, directory)
        try:
            return publish_artifact()
        except Exception as artifact_error:
            try:
                _rollback_verification_sidecar(
                    sidecar_path,
                    directory,
                    prior_sidecar,
                    published_sidecar,
                )
            except Exception as rollback_error:
                raise ExceptionGroup(
                    "Artifact publication failed and verification sidecar rollback failed",
                    [artifact_error, rollback_error],
                ) from None
            raise


def _read_verification_sidecar_snapshot(path: Path, root: Path) -> bytes | None:
    """Read stable bounded sidecar bytes before a synthesis transaction."""

    initial_identity = confined_file_identity(path, root)
    if initial_identity is None:
        return None
    content = read_confined_state_bytes(
        path,
        root,
        max_bytes=_MAX_VERIFY_SIDECAR_BYTES,
    )
    if content is None or confined_file_identity(path, root) != initial_identity:
        raise ConfinedStateError(f"Verification sidecar changed while it was read: {path}")
    return content


def _rollback_verification_sidecar(
    path: Path,
    root: Path,
    prior_content: bytes | None,
    published_identity: FileIdentity | None,
) -> None:
    """Restore the prior artifact binding after synthesis publication fails."""

    if prior_content is None:
        if published_identity is not None:
            unlink_confined_file(path, root, expected=published_identity)
        return
    if published_identity is None:
        atomic_write_confined_bytes(path, prior_content, root, exclusive=True)
        return
    atomic_write_confined_bytes(
        path,
        prior_content,
        root,
        expected=published_identity,
    )


def _inferred_entailment_status(entailment: EntailmentReport | None) -> EntailmentStatus:
    if entailment is None:
        return "not_required"
    if entailment.checked == 0:
        return "incomplete"
    if entailment.flagged:
        return "flagged"
    return "passed"


def _entailment_sidecar_payload(
    entailment: EntailmentReport | None,
    status: EntailmentStatus | None,
    reason: str,
) -> dict[str, object] | None:
    resolved = status or _inferred_entailment_status(entailment)
    if resolved == "passed" and (
        entailment is None or entailment.checked <= 0 or entailment.flagged
    ):
        raise ValueError("passed entailment status requires a complete clean report")
    if resolved == "flagged" and (entailment is None or not entailment.flagged):
        raise ValueError("flagged entailment status requires flagged claims")
    if resolved == "incomplete" and (entailment is None or entailment.checked != 0):
        raise ValueError("incomplete entailment status requires a zero-coverage report")
    if resolved in {"not_required", "unavailable", "error"} and entailment is not None:
        raise ValueError(f"{resolved} entailment status cannot carry a report")
    if resolved == "not_required":
        return None
    payload: dict[str, object] = {
        "status": resolved,
        "checked": entailment.checked if entailment is not None else 0,
        "supported": entailment.supported if entailment is not None else 0,
        "flagged": list(entailment.flagged) if entailment is not None else [],
        "model": entailment.model if entailment is not None else "",
        "threshold": entailment.threshold if entailment is not None else None,
    }
    if reason:
        payload["reason"] = reason
    return payload


def write_verify_sidecar(
    directory: Path,
    report: VerifyReport,
    *,
    identity: str | None = None,
    insight_name: str = "",
    insight_sha256: str | None = None,
    source_name: str = "",
    entailment: EntailmentReport | None = None,
    entailment_status: EntailmentStatus | None = None,
    entailment_reason: str = "",
) -> Path:
    """Write the ``<stem>_Verify.json`` sidecar next to the insight artifact."""
    if insight_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", insight_sha256) is None:
        raise ValueError("insight_sha256 must be a lowercase SHA-256 hex digest")
    path = artifact_path(directory, "verify", identity=identity, extension="json")
    payload: dict[str, object] = {
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
    if insight_sha256 is not None:
        payload["insight_sha256"] = insight_sha256
    entailment_payload = _entailment_sidecar_payload(
        entailment, entailment_status, entailment_reason
    )
    if entailment_payload is not None:
        payload["entailment"] = entailment_payload
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")
    return path
