# pyright: strict
"""Fixed-seed, disposable corpus generator for scale measurements."""

from __future__ import annotations

import hashlib
import json
import random
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from distill.config import DistillConfig
from distill.library.paths import apply_frontmatter, artifact_path, slugify_title

CORPUS_SCHEMA_VERSION = "corpus-scale-corpus.v1"
DEFAULT_SEED = 20260711
DEFAULT_TOPIC = "benchmark-scale"
_BODY_WORDS = 120


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    """Stable identity and expected shape of one generated corpus."""

    schema_version: str
    seed: int
    scale: int
    topic: str
    source_counts: dict[str, int]
    duplicate_groups: int
    total_links: int
    broken_links: int
    files: int
    bytes: int
    digest_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "scale": self.scale,
            "topic": self.topic,
            "source_counts": dict(sorted(self.source_counts.items())),
            "duplicate_groups": self.duplicate_groups,
            "total_links": self.total_links,
            "broken_links": self.broken_links,
            "files": self.files,
            "bytes": self.bytes,
            "digest_sha256": self.digest_sha256,
        }


@dataclass(frozen=True, slots=True)
class GeneratedCorpus:
    """Paths and contract data for a corpus owned by a temporary workspace."""

    workspace: Path
    library_root: Path
    config: DistillConfig
    topic: str
    manifest: CorpusManifest

    @property
    def topic_dir(self) -> Path:
        return self.config.topic_dir(self.topic)


@dataclass(frozen=True, slots=True)
class _SourceSpec:
    index: int
    source_type: str
    source_id: str
    title: str
    directory: Path
    insight_path: Path
    receipt_path: Path


def corpus_tree_digest(library_root: Path) -> str:
    """Hash sorted relative paths and file bytes, independent of temp location."""
    digest = hashlib.sha256()
    for path in sorted(item for item in library_root.rglob("*") if item.is_file()):
        relative = path.relative_to(library_root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _tree_size(library_root: Path) -> tuple[int, int]:
    files = [item for item in library_root.rglob("*") if item.is_file()]
    return len(files), sum(item.stat().st_size for item in files)


def _assert_within(path: Path, root: Path) -> None:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Benchmark path escaped its disposable workspace: {path}")


def _write_text(path: Path, text: str, *, root: Path) -> None:
    _assert_within(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_json(path: Path, value: object, *, root: Path) -> None:
    _write_text(
        path,
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        root=root,
    )


def _source_type(index: int) -> str:
    bucket = index % 10
    if bucket < 4:
        return "video"
    if bucket < 7:
        return "site"
    if bucket < 9:
        return "paper"
    return "x"


def _source_spec(config: DistillConfig, index: int) -> _SourceSpec:
    source_type = _source_type(index)
    source_id = f"source{index:08d}"
    title = f"Benchmark {source_type.title()} {index:05d}"
    if source_type == "video":
        directory = config.video_dir_slug(
            DEFAULT_TOPIC,
            f"Benchmark Channel {index % 8:02d}",
            title,
            source_id,
        )
        receipt_type = "transcript"
        extension = "txt"
    elif source_type == "site":
        directory = config.site_page_dir(
            DEFAULT_TOPIC,
            f"example-{index % 6}.test",
            title,
            source_id,
        )
        receipt_type = "content"
        extension = "md"
    elif source_type == "paper":
        directory = config.paper_dir(DEFAULT_TOPIC, title, source_id)
        receipt_type = "paper"
        extension = "md"
    else:
        handle = f"account-{index % 5}"
        directory = (
            config.topic_dir(DEFAULT_TOPIC)
            / "x"
            / handle
            / "posts"
            / slugify_title(title, source_id)
        )
        receipt_type = "tweet"
        extension = "md"
    return _SourceSpec(
        index=index,
        source_type=source_type,
        source_id=source_id,
        title=title,
        directory=directory,
        insight_path=artifact_path(directory, "insights"),
        receipt_path=artifact_path(directory, receipt_type, extension=extension),
    )


def _frontmatter(spec: _SourceSpec) -> dict[str, object]:
    return {
        "title": spec.title,
        "type": "insights",
        "topic": DEFAULT_TOPIC,
        "source": spec.source_type,
        "source_id": spec.source_id,
        "url": f"https://example.test/{spec.source_type}/{spec.source_id}",
        "prompt_id": "analysis.pass2.v2",
        "generated_at": "2026-07-11T00:00:00Z",
    }


def _body_tokens(
    spec: _SourceSpec,
    *,
    duplicate_groups: int,
    group_salts: list[int],
    document_salt: int,
) -> list[str]:
    duplicate_members = duplicate_groups * 3
    if spec.index < duplicate_members:
        group = spec.index // 3
        shared_words = int(_BODY_WORDS * 0.82)
        shared = [f"g{group}s{group_salts[group]}w{word}" for word in range(shared_words)]
        unique = [
            f"d{spec.index}s{document_salt}w{word}" for word in range(_BODY_WORDS - shared_words)
        ]
        return shared + unique
    return [f"d{spec.index}s{document_salt}w{word}" for word in range(_BODY_WORDS)]


def _insight_body(
    spec: _SourceSpec,
    *,
    tokens: list[str],
    valid_target: str,
    broken: bool,
) -> str:
    rare = " rareneedle" if spec.index == 0 else ""
    target = f"missing_{spec.index}_Insights" if broken else valid_target
    return (
        f"# {spec.title}\n\n"
        f"commonneedle{rare} records deterministic benchmark evidence.\n\n"
        f"{' '.join(tokens)}\n\n"
        f"Related evidence: [[{target}|benchmark source]].\n"
    )


def _receipt_body(spec: _SourceSpec, document_salt: int) -> str:
    words = " ".join(
        f"receipt{spec.index}s{document_salt}w{word}" for word in range(_BODY_WORDS * 2)
    )
    return f"# Receipt for {spec.title}\n\n{words}\n"


def _write_source(
    spec: _SourceSpec,
    *,
    body: str,
    receipt: str,
    library_root: Path,
) -> None:
    _write_text(
        spec.insight_path,
        apply_frontmatter(body, _frontmatter(spec)),
        root=library_root,
    )
    _write_text(spec.receipt_path, receipt, root=library_root)
    _write_json(
        spec.directory / "metadata.json",
        {
            "analysis_mode": "scan" if spec.index % 4 == 0 else "full",
            "duration": 900 + spec.index,
            "source_id": spec.source_id,
            "title": spec.title,
            "url": f"https://example.test/{spec.source_type}/{spec.source_id}",
        },
        root=library_root,
    )
    _write_json(
        artifact_path(spec.directory, "verify", extension="json"),
        {"checked": 1, "schema_version": 2, "supported": 1, "unsupported": []},
        root=library_root,
    )


def _write_topic_outputs(config: DistillConfig, library_root: Path) -> None:
    topic_dir = config.topic_dir(DEFAULT_TOPIC)
    fixed_frontmatter = {
        "title": "Benchmark scale synthesis",
        "type": "topic_synthesis",
        "topic": DEFAULT_TOPIC,
        "source": "distill",
        "generated_at": "2026-07-11T00:00:00Z",
    }
    _write_text(topic_dir / "AGENTS.md", "# Benchmark topic\n", root=library_root)
    _write_text(topic_dir / "CLAUDE.md", "# Benchmark topic\n", root=library_root)
    _write_text(
        artifact_path(topic_dir, "topic_synthesis", identity=DEFAULT_TOPIC),
        apply_frontmatter(
            "# Benchmark synthesis\n\ncommonneedle summarizes the generated corpus.\n",
            fixed_frontmatter,
        ),
        root=library_root,
    )


def _build_corpus(workspace: Path, *, scale: int, seed: int) -> GeneratedCorpus:
    if scale < 1:
        raise ValueError("scale must be at least 1")
    library_root = workspace / "library"
    config = DistillConfig(distill_output_dir=library_root)
    _write_json(
        workspace / ".distill-benchmark.json",
        {"schema_version": CORPUS_SCHEMA_VERSION},
        root=workspace,
    )
    _write_json(
        library_root / "library.json",
        {"topics": {}, "topic_watchlist": [], "watchlist": []},
        root=library_root,
    )
    _write_topic_outputs(config, library_root)

    specs = [_source_spec(config, index) for index in range(scale)]
    duplicate_groups = scale // 20
    rng = random.Random(seed)
    group_salts = [rng.randrange(1_000_000, 9_999_999) for _ in range(duplicate_groups)]
    document_salts = [rng.randrange(1_000_000, 9_999_999) for _ in range(scale)]
    valid_target = specs[0].insight_path.stem
    broken_links = 0
    source_counts = {"paper": 0, "site": 0, "video": 0, "x": 0}

    for spec in specs:
        broken = spec.index % 17 == 0
        broken_links += int(broken)
        source_counts[spec.source_type] += 1
        tokens = _body_tokens(
            spec,
            duplicate_groups=duplicate_groups,
            group_salts=group_salts,
            document_salt=document_salts[spec.index],
        )
        _write_source(
            spec,
            body=_insight_body(
                spec,
                tokens=tokens,
                valid_target=valid_target,
                broken=broken,
            ),
            receipt=_receipt_body(spec, document_salts[spec.index]),
            library_root=library_root,
        )

    files, byte_count = _tree_size(library_root)
    manifest = CorpusManifest(
        schema_version=CORPUS_SCHEMA_VERSION,
        seed=seed,
        scale=scale,
        topic=DEFAULT_TOPIC,
        source_counts=source_counts,
        duplicate_groups=duplicate_groups,
        total_links=scale,
        broken_links=broken_links,
        files=files,
        bytes=byte_count,
        digest_sha256=corpus_tree_digest(library_root),
    )
    return GeneratedCorpus(
        workspace=workspace,
        library_root=library_root,
        config=config,
        topic=DEFAULT_TOPIC,
        manifest=manifest,
    )


@contextmanager
def generated_corpus(*, scale: int, seed: int = DEFAULT_SEED) -> Generator[GeneratedCorpus]:
    """Yield a generated corpus under a fresh temporary directory, then remove it.

    There is deliberately no output-path argument. The harness cannot point at,
    overwrite, or derive configuration from a user's real Distill library.
    """
    with tempfile.TemporaryDirectory(prefix="distill-corpus-scale-") as temporary:
        yield _build_corpus(Path(temporary), scale=scale, seed=seed)
