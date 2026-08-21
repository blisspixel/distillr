# pyright: strict
"""Run live release journeys with fail-closed cost and evidence checks."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import platform
import re
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, TypedDict, cast
from urllib.parse import urlparse

import psutil

from benchmarks.user_experience.runner import source_fingerprint
from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import normalize_youtube_channel_url
from distill.library import Library
from distill.library.insights import discover_insights, verify_sidecar_for_insight
from distill.library.verify_sidecar import parse_verify_sidecar
from distill.pipeline.audit import collect_verify_rollup

CAMPAIGN_SCHEMA_VERSION = "live-journey-campaign.v1"
RESULT_SCHEMA_VERSION = "live-journey-result.v1"
MAX_AUTHORIZED_PAID_USD = 5.0
REQUIRED_KINDS = ("papers", "videos", "site-batch")
_MARKER_NAME = ".distill-live-evidence-root.json"
_ID_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
_SECRET_NAME_RE = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.I)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PROBE_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_PROBE_TIMEOUT_SECONDS = 600
_PROBE_OUTPUT_TOKENS = 128


class ProcessEvidence(TypedDict):
    wall_ns: int
    cpu_ns: int
    peak_rss_bytes: int
    returncode: int
    stdout_bytes: int
    stdout_sha256: str
    stderr_bytes: int
    stderr_sha256: str


@dataclass(frozen=True, slots=True)
class Journey:
    id: str
    kind: str
    topic: str
    expected_items: int
    timeout_seconds: int
    max_attempts: int
    query: str = ""
    sort: str = "relevance"
    expand: bool = True
    rerank: bool = True
    workers: int = 1
    channel_url: str = ""
    channel_name: str = ""
    days: int = 0
    include_shorts: bool = False
    urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Campaign:
    id: str
    provider: str
    model: str
    verification_mode: str
    max_paid_usd: float
    minimum_decode_tokens_per_second: float
    journeys: tuple[Journey, ...]
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class _Offsets:
    phase: int
    provider: int
    cost: int
    run: int


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object with string keys")
    raw = cast("dict[object, object]", value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{label} must be an object with string keys")
    return {cast("str", key): item for key, item in raw.items()}


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _identifier(value: object, label: str) -> str:
    parsed = _text(value, label)
    if _ID_RE.fullmatch(parsed) is None:
        raise ValueError(f"{label} is not a portable identifier")
    return parsed


def _integer(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def _non_negative_number(value: object, label: str, *, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or parsed > maximum:
        raise ValueError(f"{label} must be from 0 through {maximum:g}")
    return parsed


def _url(value: object, label: str, *, youtube: bool = False) -> str:
    parsed = _text(value, label)
    if youtube:
        normalized = normalize_youtube_channel_url(parsed)
        if not normalized:
            raise ValueError(f"{label} must be a valid YouTube channel URL")
        return normalized
    parts = urlparse(parsed)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"{label} must be an HTTPS URL without user information")
    return parsed


def _keys(data: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {', '.join(sorted(unknown))}")


def _journey(value: object) -> Journey:
    data = _object(value, "journey")
    common = {
        "id",
        "kind",
        "topic",
        "expected_items",
        "timeout_seconds",
        "max_attempts",
    }
    kind = _text(data.get("kind"), "journey.kind")
    expected = _integer(
        data.get("expected_items"), "journey.expected_items", minimum=1, maximum=100
    )
    journey_id = _identifier(data.get("id"), "journey.id")
    topic = _identifier(data.get("topic"), "journey.topic")
    timeout_seconds = _integer(
        data.get("timeout_seconds", 43_200),
        "journey.timeout_seconds",
        minimum=60,
        maximum=86_400,
    )
    max_attempts = _integer(
        data.get("max_attempts", 2),
        "journey.max_attempts",
        minimum=1,
        maximum=3,
    )
    if kind == "papers":
        _keys(data, common | {"query", "sort", "expand", "rerank", "workers"}, "papers journey")
        if expected != 20:
            raise ValueError("the papers reference journey must request exactly 20 items")
        sort = _text(data.get("sort", "relevance"), "journey.sort")
        if sort not in {"relevance", "date"}:
            raise ValueError("journey.sort must be relevance or date")
        return Journey(
            id=journey_id,
            kind=kind,
            topic=topic,
            expected_items=expected,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            query=_text(data.get("query"), "journey.query"),
            sort=sort,
            expand=_boolean(data.get("expand", True), "journey.expand"),
            rerank=_boolean(data.get("rerank", True), "journey.rerank"),
            workers=_integer(data.get("workers", 1), "journey.workers", minimum=1, maximum=3),
        )
    if kind == "videos":
        _keys(
            data,
            common | {"channel_url", "channel_name", "days", "include_shorts"},
            "videos journey",
        )
        if expected != 50:
            raise ValueError("the videos reference journey must request exactly 50 items")
        return Journey(
            id=journey_id,
            kind=kind,
            topic=topic,
            expected_items=expected,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            channel_url=_url(data.get("channel_url"), "journey.channel_url", youtube=True),
            channel_name=_text(data.get("channel_name"), "journey.channel_name"),
            days=_integer(data.get("days"), "journey.days", minimum=1, maximum=3650),
            include_shorts=_boolean(data.get("include_shorts", False), "journey.include_shorts"),
        )
    if kind == "site-batch":
        _keys(data, common | {"urls"}, "site-batch journey")
        raw_urls = data.get("urls")
        if not isinstance(raw_urls, list) or not raw_urls:
            raise ValueError("site-batch journey.urls must be a non-empty list")
        url_values = cast("list[object]", raw_urls)
        urls = tuple(_url(item, f"journey.urls[{index}]") for index, item in enumerate(url_values))
        if len(urls) != len(set(urls)) or expected != len(urls):
            raise ValueError("site-batch expected_items must equal the unique URL count")
        return Journey(
            id=journey_id,
            kind=kind,
            topic=topic,
            expected_items=expected,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            urls=urls,
        )
    raise ValueError(f"unsupported live journey kind: {kind}")


def load_campaign(path: Path) -> Campaign:  # noqa: C901 - strict union manifest parser
    """Load a strict local-only campaign without accepting ambiguous cost routes."""

    payload = path.read_bytes()
    if len(payload) > 256 * 1024:
        raise ValueError("campaign manifest is too large")
    raw: object = json.loads(payload)
    data = _object(raw, "campaign")
    _keys(
        data,
        {
            "schema_version",
            "campaign_id",
            "cost_mode",
            "max_paid_usd",
            "provider",
            "model",
            "minimum_decode_tokens_per_second",
            "verification_mode",
            "journeys",
        },
        "campaign",
    )
    if data.get("schema_version") != CAMPAIGN_SCHEMA_VERSION:
        raise ValueError(f"campaign schema must be {CAMPAIGN_SCHEMA_VERSION}")
    if data.get("cost_mode") != "no-metered":
        raise ValueError("live evidence campaigns currently require cost_mode no-metered")
    maximum = data.get("max_paid_usd")
    if isinstance(maximum, bool) or not isinstance(maximum, int | float):
        raise ValueError("max_paid_usd must be numeric")
    maximum = float(maximum)
    if not math.isfinite(maximum) or maximum != 0 or maximum > MAX_AUTHORIZED_PAID_USD:
        raise ValueError("no-metered live evidence requires max_paid_usd 0")
    provider = _text(data.get("provider"), "campaign.provider").casefold()
    if provider not in {"ollama", "lmstudio"}:
        raise ValueError("no-metered live evidence requires ollama or lmstudio")
    verification = _text(data.get("verification_mode", "warn"), "verification_mode")
    if verification not in {"warn", "strict"}:
        raise ValueError("verification_mode must be warn or strict")
    raw_journeys = data.get("journeys")
    if not isinstance(raw_journeys, list):
        raise ValueError("campaign.journeys must be a list")
    journeys = tuple(_journey(item) for item in cast("list[object]", raw_journeys))
    kinds = [item.kind for item in journeys]
    ids = [item.id for item in journeys]
    if tuple(sorted(kinds)) != tuple(sorted(REQUIRED_KINDS)) or len(journeys) != 3:
        raise ValueError("campaign must contain one papers, one videos, and one site-batch journey")
    if len(ids) != len(set(ids)) or len({item.topic for item in journeys}) != len(journeys):
        raise ValueError("journey ids and topics must be unique")
    return Campaign(
        id=_identifier(data.get("campaign_id"), "campaign.campaign_id"),
        provider=provider,
        model=_text(data.get("model"), "campaign.model"),
        verification_mode=verification,
        max_paid_usd=maximum,
        minimum_decode_tokens_per_second=_non_negative_number(
            data.get("minimum_decode_tokens_per_second", 0),
            "minimum_decode_tokens_per_second",
            maximum=1_000,
        ),
        journeys=journeys,
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _loopback_endpoint(provider: str) -> str:
    variable = "OLLAMA_BASE_URL" if provider == "ollama" else "LMSTUDIO_BASE_URL"
    default = "http://127.0.0.1:11434" if provider == "ollama" else "http://127.0.0.1:1234"
    endpoint = os.environ.get(variable, default).rstrip("/")
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{provider} evidence endpoint must be a root HTTP loopback URL without credentials"
        )
    try:
        _port = parsed.port
    except ValueError:
        raise ValueError(f"{provider} evidence endpoint has an invalid port") from None
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.casefold() != "localhost":
            raise ValueError(f"{provider} evidence endpoint must be loopback") from None
    else:
        if not address.is_loopback:
            raise ValueError(f"{provider} evidence endpoint must be loopback")
    return endpoint


def _open_loopback(request: urllib.request.Request, *, timeout: float) -> Any:
    """Open a verified loopback request without consulting proxy configuration."""

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def _ollama_throughput_probe(
    endpoint: str,
    campaign: Campaign,
) -> dict[str, object]:
    prompt = (
        "Return a compact JSON object with a summary and confidence after reviewing "
        "this bounded local throughput probe."
    )
    payload = json.dumps(
        {
            "model": campaign.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {
                "num_ctx": 4096,
                "num_predict": _PROBE_OUTPUT_TOKENS,
                "temperature": 0,
            },
        },
        separators=(",", ":"),
    ).encode()
    request = urllib.request.Request(
        f"{endpoint}/api/chat",
        data=payload,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with _open_loopback(request, timeout=_PROBE_TIMEOUT_SECONDS) as response:
        raw = response.read(_PROBE_MAX_RESPONSE_BYTES + 1)
    wall_seconds = time.perf_counter() - started
    if not raw or len(raw) > _PROBE_MAX_RESPONSE_BYTES:
        raise ValueError("Ollama throughput probe returned an invalid response size")
    data = _object(json.loads(raw), "Ollama throughput probe")
    if data.get("model") != campaign.model or data.get("done") is not True:
        raise ValueError("Ollama throughput probe did not complete with the exact model")
    output_tokens = data.get("eval_count")
    decode_ns = data.get("eval_duration")
    input_tokens = data.get("prompt_eval_count")
    prefill_ns = data.get("prompt_eval_duration")
    if (
        not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
        or output_tokens <= 0
        or not isinstance(decode_ns, int)
        or isinstance(decode_ns, bool)
        or decode_ns <= 0
        or not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or input_tokens < 0
        or not isinstance(prefill_ns, int)
        or isinstance(prefill_ns, bool)
        or prefill_ns < 0
    ):
        raise ValueError("Ollama throughput probe omitted valid reported token timing")
    decode_rate = output_tokens / (decode_ns / 1_000_000_000)
    minimum = campaign.minimum_decode_tokens_per_second
    if decode_rate < minimum:
        raise ValueError(
            "Ollama model decode throughput is below the campaign minimum: "
            f"{decode_rate:.2f} < {minimum:.2f} tokens/s"
        )
    return {
        "status": "ok",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "prefill_seconds": round(prefill_ns / 1_000_000_000, 6),
        "decode_seconds": round(decode_ns / 1_000_000_000, 6),
        "decode_tokens_per_second": round(decode_rate, 6),
        "minimum_decode_tokens_per_second": minimum,
        "wall_seconds": round(wall_seconds, 6),
        "usage_source": "ollama-reported",
    }


def provider_preflight(campaign: Campaign) -> dict[str, object]:
    """Prove that the selected exact model is present on a loopback endpoint."""

    endpoint = _loopback_endpoint(campaign.provider)
    url = f"{endpoint}/api/tags" if campaign.provider == "ollama" else f"{endpoint}/v1/models"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with _open_loopback(request, timeout=5) as response:
        payload: object = json.loads(response.read(4 * 1024 * 1024))
    data = _object(payload, "provider preflight")
    if campaign.provider == "ollama":
        raw_models = data.get("models")
        if not isinstance(raw_models, list):
            raise ValueError("Ollama preflight returned no model list")
        models = [_object(item, "Ollama model") for item in cast("list[object]", raw_models)]
        match = next((item for item in models if item.get("name") == campaign.model), None)
        if match is None:
            raise ValueError(f"Ollama model is not installed: {campaign.model}")
        size = match.get("size")
        digest = match.get("digest", "")
    else:
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise ValueError("LM Studio preflight returned no model list")
        models = [_object(item, "LM Studio model") for item in cast("list[object]", raw_models)]
        match = next((item for item in models if item.get("id") == campaign.model), None)
        if match is None:
            raise ValueError(f"LM Studio model is not installed: {campaign.model}")
        size = None
        digest = ""
    result: dict[str, object] = {
        "status": "ok",
        "provider": campaign.provider,
        "model": campaign.model,
        "endpoint_class": "http-loopback",
        "model_size_bytes": size if isinstance(size, int) and size >= 0 else None,
        "model_digest": digest if isinstance(digest, str) and _SHA256_RE.fullmatch(digest) else "",
        "no_metered_cost_proven_by": "local-loopback-topology",
    }
    if campaign.minimum_decode_tokens_per_second > 0:
        if campaign.provider != "ollama":
            raise ValueError("decode throughput preflight currently requires Ollama")
        result["throughput_probe"] = _ollama_throughput_probe(endpoint, campaign)
    return result


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _environment(campaign: Campaign, executable: Path) -> dict[str, object]:
    fingerprint, count = source_fingerprint()
    memory = psutil.virtual_memory()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "operating_system": platform.system(),
        "platform_release": platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": psutil.cpu_count(),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "memory_bytes": int(memory.total),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "distill_version": version("distillr"),
        "distill_executable_name": executable.name,
        "distill_executable_bytes": executable.stat().st_size,
        "distill_executable_sha256": _file_sha256(executable),
        "source_fingerprint_sha256": fingerprint,
        "source_file_count": count,
        "provider": campaign.provider,
        "model": campaign.model,
    }


def _command_environment(campaign: Campaign, library: Path, scratch: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if _SECRET_NAME_RE.search(key) is None and not key.startswith("COV_CORE_")
    }
    environment.pop("DISTILL_COST_WORKFLOW_BUDGETS", None)
    environment.update(
        {
            "DISTILL_OUTPUT_DIR": str(library),
            "DISTILL_PROVIDER": campaign.provider,
            "DISTILL_MODEL": campaign.model,
            "DISTILL_COST_MODE": "no-metered",
            "DISTILL_VERIFY": campaign.verification_mode,
            "DISTILL_NO_PREFLIGHT": "1",
            "DISTILL_NO_UPDATE_CHECK": "1",
            "NO_COLOR": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "TMPDIR": str(scratch),
        }
    )
    if os.name == "nt":
        environment["TEMP"] = str(scratch)
        environment["TMP"] = str(scratch)
    return environment


def _marker(campaign: Campaign) -> dict[str, object]:
    return {
        "schema_version": 1,
        "campaign_id": campaign.id,
        "manifest_sha256": campaign.manifest_sha256,
        "purpose": "disposable-live-release-evidence",
    }


def prepare_library(campaign: Campaign, library: Path) -> None:
    """Create or verify the exact marked disposable library used by a campaign."""

    resolved = library.resolve()
    marker_path = resolved / _MARKER_NAME
    expected = _marker(campaign)
    if resolved.exists():
        if not resolved.is_dir():
            raise ValueError("live evidence library is not a directory")
        if marker_path.exists():
            if json.loads(marker_path.read_text(encoding="utf-8")) != expected:
                raise ValueError("live evidence library marker does not match the campaign")
            return
        if any(resolved.iterdir()):
            raise ValueError("refusing an unmarked non-empty live evidence library")
    resolved.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    config = DistillConfig(distill_output_dir=resolved)
    library_state = Library(config)
    for journey in campaign.journeys:
        if journey.kind == "videos":
            added = library_state.add_to_watchlist(
                journey.channel_url,
                journey.channel_name,
                topic=journey.topic,
                instructions="Analyze the source faithfully and preserve important claims.",
                days=journey.days,
            )
            if not added:
                existing = [
                    item
                    for item in library_state.get_watchlist()
                    if item.name == journey.channel_name
                ]
                if len(existing) != 1 or existing[0].url != journey.channel_url:
                    raise ValueError(
                        "existing live evidence watch entry does not match the manifest"
                    )


def _site_seed_file(campaign: Campaign, journey: Journey, library: Path) -> Path:
    inputs = library / ".distill" / "evidence-inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    path = inputs / f"{journey.id}.json"
    payload = {
        "topic": journey.topic,
        "urls": [
            {
                "url": url,
                "topic": journey.topic,
                "max_depth": 0,
                "max_pages": 1,
            }
            for url in journey.urls
        ],
    }
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ValueError("site-batch evidence input changed after campaign preparation")
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _command(
    executable: Path,
    campaign: Campaign,
    journey: Journey,
    library: Path,
    remaining: int,
) -> list[str]:
    prefix = [str(executable), "--cost-mode", "no-metered"]
    if journey.kind == "papers":
        command = [
            *prefix,
            "papers",
            journey.query,
            "--topic",
            journey.topic,
            "--limit",
            str(remaining),
            "--sort",
            journey.sort,
            "--verify",
            campaign.verification_mode,
            "--workers",
            str(journey.workers),
        ]
        command.append("--expand" if journey.expand else "--no-expand")
        command.append("--rerank" if journey.rerank else "--no-rerank")
        return command
    if journey.kind == "videos":
        return [
            *prefix,
            "catch-up",
            journey.channel_name,
            "--days",
            str(journey.days),
            "--limit",
            str(remaining),
            "--shorts" if journey.include_shorts else "--no-shorts",
        ]
    return [
        *prefix,
        "site-batch",
        str(_site_seed_file(campaign, journey, library)),
        "--topic",
        journey.topic,
        "--seed-only",
    ]


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _offsets(library: Path) -> _Offsets:
    ops = library / ".distill"
    return _Offsets(
        phase=_file_size(ops / "phase_telemetry.jsonl"),
        provider=_file_size(ops / "telemetry.jsonl"),
        cost=_file_size(ops / "cost_log.jsonl"),
        run=_file_size(ops / "run_log.jsonl"),
    )


def _rows(path: Path, offset: int) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open("rb") as stream:
        stream.seek(offset)
        payload = stream.read(16 * 1024 * 1024 + 1)
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError(f"live evidence log append is too large: {path.name}")
    rows: list[dict[str, object]] = []
    for line in payload.splitlines():
        if not line.strip():
            continue
        rows.append(_object(json.loads(line), path.name))
    return rows


def _process_usage(processes: Sequence[psutil.Process]) -> tuple[int, int]:
    cpu_seconds = 0.0
    rss_bytes = 0
    for item in processes:
        try:
            usage = item.cpu_times()
            cpu_seconds += float(usage.user) + float(usage.system)
            rss_bytes += int(item.memory_info().rss)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return int(cpu_seconds * 1_000_000_000), rss_bytes


def _run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
) -> ProcessEvidence:
    started = time.perf_counter_ns()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            list(command), cwd=cwd, env=dict(environment), stdout=stdout_file, stderr=stderr_file
        )
        root = psutil.Process(process.pid)
        tree = [root]
        peak_rss = 0
        cpu_ns = 0
        next_children = 0.0
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            now = time.monotonic()
            if now >= next_children:
                tree = [root]
                with suppress(psutil.AccessDenied, psutil.NoSuchProcess):
                    tree.extend(root.children(recursive=True))
                next_children = now + 0.1
            current_cpu, current_rss = _process_usage(tree)
            cpu_ns = max(cpu_ns, current_cpu)
            peak_rss = max(peak_rss, current_rss)
            if now >= deadline:
                process.kill()
                process.wait()
                raise TimeoutError(f"live journey timed out after {timeout_seconds}s")
            time.sleep(0.01)
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()
    return {
        "wall_ns": time.perf_counter_ns() - started,
        "cpu_ns": cpu_ns,
        "peak_rss_bytes": peak_rss,
        "returncode": int(process.returncode),
        "stdout_bytes": len(stdout),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_bytes": len(stderr),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    }


def _source_state(library: Path, topic: str) -> dict[str, str]:
    topic_dir = library / "topics" / topic
    return {
        ref.artifact_path: ref.content_sha256
        for ref in discover_insights(topic_dir, validate_verification=True)
    }


def _tree_digest(library: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in library.rglob("*") if item.is_file()):
        relative = path.relative_to(library)
        if relative.name == _MARKER_NAME or ".distill" in relative.parts:
            continue
        name = relative.as_posix().encode()
        payload = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _verification(library: Path, topic: str, started_epoch_ns: int) -> dict[str, object]:
    topic_dir = library / "topics" / topic
    rollup = collect_verify_rollup(topic_dir)
    events: list[int] = []
    for ref in discover_insights(topic_dir, validate_verification=True):
        sidecar = verify_sidecar_for_insight(ref.path)
        try:
            sidecar_payload: object = json.loads(sidecar.read_bytes())
            parsed_sidecar = parse_verify_sidecar(sidecar_payload)
            published = max(ref.path.stat().st_mtime_ns, sidecar.stat().st_mtime_ns)
        except (OSError, RecursionError, ValueError):
            continue
        if parsed_sidecar is None:
            continue
        if published >= started_epoch_ns:
            events.append(published - started_epoch_ns)
    return {
        "insights_total": rollup.insights_total,
        "insights_checked": rollup.checked,
        "insights_clean": rollup.clean,
        "insights_flagged": len(rollup.flagged),
        "synthesis_total": rollup.synthesis_total,
        "synthesis_checked": rollup.synthesis_checked,
        "synthesis_clean": rollup.synthesis_clean,
        "time_to_first_verified_artifact_ns": min(events) if events else None,
        "time_to_final_verified_artifact_ns": max(events) if events else None,
        "new_verified_artifact_count": len(events),
        "verified_artifact_definition": "source insight with a structurally valid verification sidecar; a present content binding must match",
    }


def _correlation(library: Path, before: _Offsets) -> dict[str, object]:
    ops = library / ".distill"
    phase = _rows(ops / "phase_telemetry.jsonl", before.phase)
    provider = _rows(ops / "telemetry.jsonl", before.provider)
    cost = _rows(ops / "cost_log.jsonl", before.cost)
    runs = _rows(ops / "run_log.jsonl", before.run)
    run_ids = {
        row.get("run_id")
        for row in [*phase, *provider, *cost, *runs]
        if isinstance(row.get("run_id"), str) and row.get("run_id")
    }
    if len(run_ids) != 1:
        raise ValueError(f"live journey expected one correlated run id, found {len(run_ids)}")
    run_id = cast("str", next(iter(run_ids)))
    if len(cost) != 1 or len(runs) != 1:
        raise ValueError("live journey requires one cost row and one run summary row")
    return {
        "run_id": run_id,
        "phase_rows": phase,
        "provider_rows": provider,
        "cost_rows": cost,
        "run_rows": runs,
        "phase_rows_complete": bool(phase),
        "provider_rows_complete": bool(provider),
        "cost_rows_complete": True,
        "run_rows_complete": True,
    }


def _cost(correlation: Mapping[str, object]) -> float:
    rows = correlation.get("cost_rows")
    if not isinstance(rows, list):
        raise ValueError("missing exact cost evidence")
    cost_rows = cast("list[object]", rows)
    if len(cost_rows) != 1:
        raise ValueError("missing exact cost evidence")
    row = _object(cost_rows[0], "cost row")
    actual = row.get("actual_cost")
    if isinstance(actual, bool) or not isinstance(actual, int | float) or float(actual) != 0:
        raise ValueError("no-metered journey recorded nonzero or invalid actual cost")
    ledger = _object(row.get("usage_ledger"), "usage ledger")
    for key in (
        "metered_llm_calls",
        "metered_transcription_calls",
        "unknown_external_cost_calls",
        "unknown_external_cost_llm_calls",
        "unknown_external_cost_transcription_calls",
    ):
        if ledger.get(key) != 0:
            raise ValueError(f"no-metered journey has unsafe usage ledger field: {key}")
    providers = _object(row.get("by_provider"), "provider ledger")
    for provider in providers.values():
        details = _object(provider, "provider ledger entry")
        if details.get("no_metered_cost") is not True:
            raise ValueError("provider ledger did not prove no-metered topology")
    return 0.0


def _paid_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("live journey paid cost is invalid")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("live journey paid cost is invalid")
    return parsed


def _exact_items_complete(item: Mapping[str, object]) -> bool:
    return item.get("final_source_item_count") == item.get("expected_items")


def _no_op_complete(item: Mapping[str, object]) -> bool:
    replay = _object(item.get("no_op_probe"), "no-op probe")
    return replay.get("no_op_rate") == 1.0


def _attempt(
    executable: Path,
    campaign: Campaign,
    journey: Journey,
    library: Path,
    scratch: Path,
    remaining: int,
) -> dict[str, object]:
    command = _command(executable, campaign, journey, library, remaining)
    offsets = _offsets(library)
    before = _source_state(library, journey.topic)
    corpus_before = _tree_digest(library)
    started_epoch_ns = time.time_ns()
    process = _run_process(
        command,
        cwd=scratch,
        environment=_command_environment(campaign, library, scratch),
        timeout_seconds=journey.timeout_seconds,
    )
    if process["returncode"] != 0:
        raise ValueError(
            "live journey child failed before evidence correlation: "
            f"returncode={process['returncode']}, "
            f"stdout_sha256={process['stdout_sha256']}, "
            f"stderr_sha256={process['stderr_sha256']}"
        )
    correlation = _correlation(library, offsets)
    cost = _cost(correlation)
    after = _source_state(library, journey.topic)
    return {
        "command": command[1:],
        "started_at": datetime.fromtimestamp(started_epoch_ns / 1e9, UTC).isoformat(),
        "requested_remaining_items": remaining,
        "process": process,
        "correlation": correlation,
        "actual_paid_usd": cost,
        "source_items_before": len(before),
        "source_items_after": len(after),
        "source_items_added": len(set(after) - set(before)),
        "source_items_changed": sum(
            before.get(path) != digest for path, digest in after.items() if path in before
        ),
        "verification": _verification(library, journey.topic, started_epoch_ns),
        "corpus_digest_before": corpus_before,
        "corpus_digest_after": _tree_digest(library),
    }


def _paper_ids(library: Path, topic: str) -> list[str]:
    ids: list[str] = []
    for path in sorted((library / "topics" / topic / "papers").glob("*/metadata.json")):
        try:
            data = _object(json.loads(path.read_text(encoding="utf-8")), "paper metadata")
        except (OSError, RecursionError, UnicodeError, ValueError):
            continue
        paper_id = data.get("paper_id")
        if isinstance(paper_id, str) and paper_id and paper_id not in ids:
            ids.append(paper_id)
    return ids


def _no_op_probe(
    executable: Path,
    campaign: Campaign,
    journey: Journey,
    library: Path,
    scratch: Path,
) -> dict[str, object]:
    before = _source_state(library, journey.topic)
    probes: list[ProcessEvidence] = []
    if journey.kind == "papers":
        ids = _paper_ids(library, journey.topic)
        if len(ids) != journey.expected_items:
            raise ValueError("paper no-op probe requires one exact id per completed paper")
        commands = [
            [
                str(executable),
                "--cost-mode",
                "no-metered",
                "paper",
                paper_id,
                "--topic",
                journey.topic,
            ]
            for paper_id in ids
        ]
    else:
        commands = [_command(executable, campaign, journey, library, journey.expected_items)]
    for command in commands:
        result = _run_process(
            command,
            cwd=scratch,
            environment=_command_environment(campaign, library, scratch),
            timeout_seconds=min(journey.timeout_seconds, 1800),
        )
        if result["returncode"] != 0:
            raise ValueError("no-op probe command failed")
        probes.append(result)
    after = _source_state(library, journey.topic)
    unchanged = sum(before.get(path) == digest for path, digest in after.items() if path in before)
    return {
        "policy": "exact-item-replay" if journey.kind == "papers" else "same-command-replay",
        "process_count": len(probes),
        "total_wall_ns": sum(item["wall_ns"] for item in probes),
        "max_peak_rss_bytes": max((item["peak_rss_bytes"] for item in probes), default=0),
        "items_before": len(before),
        "items_after": len(after),
        "unchanged_items": unchanged,
        "new_items": len(set(after) - set(before)),
        "changed_items": sum(
            before.get(path) != digest for path, digest in after.items() if path in before
        ),
        "no_op_rate": unchanged / len(before) if before else 0.0,
    }


def _journey_result(
    executable: Path,
    campaign: Campaign,
    journey: Journey,
    library: Path,
    scratch: Path,
) -> dict[str, object]:
    if _source_state(library, journey.topic):
        raise ValueError(f"journey topic must be empty before its first run: {journey.topic}")
    journey_started_epoch_ns = time.time_ns()
    attempts: list[dict[str, object]] = []
    for _ in range(journey.max_attempts):
        current = len(_source_state(library, journey.topic))
        if current >= journey.expected_items:
            break
        attempts.append(
            _attempt(
                executable,
                campaign,
                journey,
                library,
                scratch,
                journey.expected_items - current,
            )
        )
    final = _source_state(library, journey.topic)
    if len(final) != journey.expected_items:
        raise ValueError(
            f"{journey.id} completed {len(final)} of {journey.expected_items} required items"
        )
    if any(cast("ProcessEvidence", item["process"])["returncode"] != 0 for item in attempts):
        raise ValueError(f"{journey.id} had a failed process attempt")
    replay = _no_op_probe(executable, campaign, journey, library, scratch)
    if replay["new_items"] or replay["changed_items"] or replay["no_op_rate"] != 1.0:
        raise ValueError(f"{journey.id} no-op replay changed authoritative source insights")
    total_paid = sum(_paid_value(item.get("actual_paid_usd")) for item in attempts)
    primary_count = (
        _integer(
            attempts[0].get("source_items_after"),
            "primary source item count",
            minimum=0,
            maximum=journey.expected_items,
        )
        if attempts
        else 0
    )
    journey_verification = _verification(
        library,
        journey.topic,
        journey_started_epoch_ns,
    )
    return {
        "id": journey.id,
        "kind": journey.kind,
        "topic": journey.topic,
        "expected_items": journey.expected_items,
        "status": "complete",
        "attempt_count": len(attempts),
        "retry_count": max(0, len(attempts) - 1),
        "retry_attempt_rate": max(0, len(attempts) - 1) / len(attempts) if attempts else 0.0,
        "primary_completion_rate": primary_count / journey.expected_items,
        "resume_completion_rate": (len(final) - primary_count) / journey.expected_items,
        "attempts": attempts,
        "no_op_probe": replay,
        "actual_paid_usd": total_paid,
        "total_primary_wall_ns": sum(
            cast("ProcessEvidence", item["process"])["wall_ns"] for item in attempts
        ),
        "max_primary_peak_rss_bytes": max(
            (cast("ProcessEvidence", item["process"])["peak_rss_bytes"] for item in attempts),
            default=0,
        ),
        "verification": journey_verification,
        "final_source_item_count": len(final),
        "final_source_digest": hashlib.sha256(
            json.dumps(final, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def run_one_journey(
    manifest: Path,
    library: Path,
    executable: Path,
    journey_id: str,
) -> dict[str, object]:
    """Run and persist one independently selectable live reference journey."""

    campaign = load_campaign(manifest)
    selected = [journey for journey in campaign.journeys if journey.id == journey_id]
    if len(selected) != 1:
        raise ValueError(f"campaign has no unique journey named {journey_id}")
    executable = executable.resolve(strict=True)
    if not executable.is_file():
        raise ValueError("distill executable is not a file")
    preflight = provider_preflight(campaign)
    prepare_library(campaign, library)
    with tempfile.TemporaryDirectory(prefix="distill-live-evidence-") as temporary:
        scratch = Path(temporary).resolve()
        journey = _journey_result(
            executable,
            campaign,
            selected[0],
            library.resolve(),
            scratch,
        )
    actual_paid = _paid_value(journey.get("actual_paid_usd"))
    if actual_paid != 0 or actual_paid > campaign.max_paid_usd:
        raise ValueError("journey paid spend exceeded its fail-closed zero-dollar contract")
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "suite": "live-reference-journey",
        "generated_at": datetime.now(UTC).isoformat(),
        "campaign": {
            "id": campaign.id,
            "manifest_sha256": campaign.manifest_sha256,
            "cost_mode": "no-metered",
            "max_paid_usd": campaign.max_paid_usd,
            "actual_paid_usd": actual_paid,
            "verification_mode": campaign.verification_mode,
        },
        "provider_preflight": preflight,
        "environment": _environment(campaign, executable),
        "journey": journey,
        "verification": {
            "journey_complete": journey.get("status") == "complete",
            "exact_item_count": _exact_items_complete(journey),
            "no_op_rate": _object(journey.get("no_op_probe"), "no-op probe").get("no_op_rate"),
            "metered_calls": 0,
            "unknown_external_cost_calls": 0,
            "actual_paid_usd": actual_paid,
            "spend_cap_usd": campaign.max_paid_usd,
        },
    }


def run_campaign(manifest: Path, library: Path, executable: Path) -> dict[str, object]:
    """Run all three live journeys and return a self-contained strict receipt."""

    campaign = load_campaign(manifest)
    executable = executable.resolve(strict=True)
    if not executable.is_file():
        raise ValueError("distill executable is not a file")
    preflight = provider_preflight(campaign)
    prepare_library(campaign, library)
    with tempfile.TemporaryDirectory(prefix="distill-live-evidence-") as temporary:
        scratch = Path(temporary).resolve()
        journeys = [
            _journey_result(executable, campaign, journey, library.resolve(), scratch)
            for journey in campaign.journeys
        ]
    actual_paid = sum(_paid_value(item.get("actual_paid_usd")) for item in journeys)
    if actual_paid != 0 or actual_paid > campaign.max_paid_usd:
        raise ValueError("campaign paid spend exceeded its fail-closed zero-dollar contract")
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "suite": "live-reference-journeys",
        "generated_at": datetime.now(UTC).isoformat(),
        "campaign": {
            "id": campaign.id,
            "manifest_sha256": campaign.manifest_sha256,
            "cost_mode": "no-metered",
            "max_paid_usd": campaign.max_paid_usd,
            "actual_paid_usd": actual_paid,
            "verification_mode": campaign.verification_mode,
        },
        "provider_preflight": preflight,
        "environment": _environment(campaign, executable),
        "journeys": journeys,
        "verification": {
            "required_journeys_complete": len(journeys) == 3,
            "exact_item_counts": all(_exact_items_complete(item) for item in journeys),
            "all_no_op_rates": all(_no_op_complete(item) for item in journeys),
            "metered_calls": 0,
            "unknown_external_cost_calls": 0,
            "actual_paid_usd": actual_paid,
            "spend_cap_usd": campaign.max_paid_usd,
        },
    }


def result_exit_code(result: Mapping[str, object]) -> int:
    raw_verification = result.get("verification")
    if not isinstance(raw_verification, dict):
        return 1
    verification = _object(cast("object", raw_verification), "verification")
    required: dict[str, object] = {
        "required_journeys_complete": True,
        "exact_item_counts": True,
        "all_no_op_rates": True,
        "metered_calls": 0,
        "unknown_external_cost_calls": 0,
        "actual_paid_usd": 0.0,
    }
    return 0 if all(verification.get(key) == value for key, value in required.items()) else 1


def single_result_exit_code(result: Mapping[str, object]) -> int:
    raw_verification = result.get("verification")
    if not isinstance(raw_verification, dict):
        return 1
    verification = _object(cast("object", raw_verification), "verification")
    required: dict[str, object] = {
        "journey_complete": True,
        "exact_item_count": True,
        "no_op_rate": 1.0,
        "metered_calls": 0,
        "unknown_external_cost_calls": 0,
        "actual_paid_usd": 0.0,
    }
    return 0 if all(verification.get(key) == value for key, value in required.items()) else 1


__all__ = [
    "CAMPAIGN_SCHEMA_VERSION",
    "MAX_AUTHORIZED_PAID_USD",
    "RESULT_SCHEMA_VERSION",
    "Campaign",
    "Journey",
    "load_campaign",
    "prepare_library",
    "provider_preflight",
    "result_exit_code",
    "run_campaign",
    "run_one_journey",
    "single_result_exit_code",
]
