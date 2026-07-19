"""Tests for strict durable source-completion ledgers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from distill.library import source_ledger


def test_source_ledger_requires_an_explicit_confinement_root(tmp_path: Path) -> None:
    path = tmp_path / "state" / "extracted_sources.json"

    with pytest.raises(TypeError, match="root"):
        source_ledger.read_source_ledger(path)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="root"):
        source_ledger.merge_source_ledger(path, ["source"])  # type: ignore[call-arg]

    assert not path.exists()


def test_source_ledger_rejects_escaping_target_before_creating_lock(tmp_path: Path) -> None:
    root = tmp_path / "topic"
    root.mkdir()
    outside = tmp_path / "outside.json"

    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="escapes"):
        source_ledger.merge_source_ledger(outside, ["source"], root=root)

    assert not outside.exists()
    assert list(root.glob(".distill-source-ledger-*.lock")) == []


def test_missing_source_ledger_is_empty(tmp_path: Path) -> None:
    assert source_ledger.read_source_ledger(tmp_path / "missing.json", root=tmp_path) == set()


@pytest.mark.parametrize("value", [None, "", 3])
def test_source_id_validation_rejects_nonempty_string_violations(value: object) -> None:
    with pytest.raises(ValueError, match="nonempty string"):
        source_ledger.validate_source_id(value)


def test_source_ledger_round_trip_and_idempotent_merge(tmp_path: Path) -> None:
    path = tmp_path / "state" / "extracted_sources.json"

    source_ledger.merge_source_ledger(path, ["b", "a"], root=tmp_path)
    source_ledger.merge_source_ledger(path, ["b", "c"], root=tmp_path)

    assert source_ledger.read_source_ledger(path, root=tmp_path) == {"a", "b", "c"}
    assert json.loads(path.read_text(encoding="utf-8")) == ["a", "b", "c"]


def test_source_ledger_preflight_accepts_exact_utf8_limit_without_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state" / "extracted_sources.json"
    exact = "\U0001f600" * (source_ledger.MAX_SOURCE_ID_BYTES // 4)

    source_ledger.ensure_source_ledger_merge_capacity(path, [exact], root=tmp_path)

    assert len(exact.encode("utf-8")) == source_ledger.MAX_SOURCE_ID_BYTES
    assert not path.exists()


def test_source_ledger_preflight_rejects_overlimit_id_without_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state" / "extracted_sources.json"
    oversized = "\U0001f600" * (source_ledger.MAX_SOURCE_ID_BYTES // 4 + 1)

    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="source-id limit"):
        source_ledger.ensure_source_ledger_merge_capacity(path, [oversized], root=tmp_path)

    assert not path.exists()


def test_source_ledger_reads_and_preserves_bounded_legacy_oversized_id(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state" / "extracted_sources.json"
    path.parent.mkdir()
    legacy = "x" * (source_ledger.MAX_SOURCE_ID_BYTES + 1)
    path.write_text(json.dumps([legacy]), encoding="utf-8")

    assert source_ledger.read_source_ledger(path, root=tmp_path) == {legacy}
    source_ledger.merge_source_ledger(path, ["current"], root=tmp_path)

    assert source_ledger.read_source_ledger(path, root=tmp_path) == {legacy, "current"}


def test_source_ledger_preflight_rejects_projected_bytes_without_touching_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "state" / "extracted_sources.json"
    source_ledger.merge_source_ledger(path, ["safe"], root=tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(source_ledger, "MAX_SOURCE_LEDGER_BYTES", len(before) + 8)

    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="serialized ledger"):
        source_ledger.ensure_source_ledger_merge_capacity(
            path,
            ["a-new-source-id"],
            root=tmp_path,
        )

    assert path.read_bytes() == before


def test_empty_merge_does_not_create_state(tmp_path: Path) -> None:
    path = tmp_path / "extracted_sources.json"

    source_ledger.merge_source_ledger(path, [], root=tmp_path)

    assert not path.exists()


def test_empty_preflight_does_not_create_state(tmp_path: Path) -> None:
    path = tmp_path / "extracted_sources.json"

    source_ledger.ensure_source_ledger_merge_capacity(path, [], root=tmp_path)

    assert not path.exists()


def test_source_ledger_enforces_input_and_projected_entry_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "extracted_sources.json"
    monkeypatch.setattr(source_ledger, "MAX_SOURCE_LEDGER_ENTRIES", 1)

    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="1-entry limit"):
        source_ledger.ensure_source_ledger_merge_capacity(path, ["a", "b"], root=tmp_path)

    path.write_text('["a"]', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="1-entry limit"):
        source_ledger.ensure_source_ledger_merge_capacity(path, ["b"], root=tmp_path)

    assert path.read_bytes() == before


def test_source_ledger_preflight_rejects_escaping_target(tmp_path: Path) -> None:
    root = tmp_path / "topic"
    root.mkdir()
    outside = tmp_path / "outside.json"

    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="escapes"):
        source_ledger.ensure_source_ledger_merge_capacity(outside, ["source"], root=root)

    assert not outside.exists()


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"", "not strict JSON"),
        (b"{}", "not a JSON array"),
        (b'["valid", 3]', "entry 2"),
        (b'["valid", ""]', "entry 2"),
        (b'["valid", "valid"]', "duplicates source ID"),
        (b'["valid", NaN]', "not strict JSON"),
        (b"\xff", "not strict JSON"),
    ],
)
def test_invalid_existing_source_ledger_fails_with_exact_path(
    tmp_path: Path,
    content: bytes,
    reason: str,
) -> None:
    path = tmp_path / "extracted_sources.json"
    path.write_bytes(content)

    with pytest.raises(source_ledger.SourceLedgerIntegrityError) as caught:
        source_ledger.read_source_ledger(path, root=tmp_path)

    assert str(path) in str(caught.value)
    assert reason in str(caught.value)


def test_source_ledger_rejects_oversized_file_and_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "extracted_sources.json"
    monkeypatch.setattr(source_ledger, "MAX_SOURCE_LEDGER_BYTES", 8)
    path.write_text('["too-long"]', encoding="utf-8")

    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="8-byte limit"):
        source_ledger.read_source_ledger(path, root=tmp_path)

    path.unlink()
    monkeypatch.setattr(source_ledger, "MAX_SOURCE_LEDGER_BYTES", 1024)
    monkeypatch.setattr(source_ledger, "MAX_SOURCE_ID_BYTES", 3)
    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="source-id limit"):
        source_ledger.merge_source_ledger(path, ["four"], root=tmp_path)
    assert not path.exists()


def test_source_ledger_rejects_symbolic_and_hard_links(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text('["safe"]', encoding="utf-8")
    symbolic = tmp_path / "symbolic.json"
    try:
        symbolic.symlink_to(target)
    except OSError:
        symbolic = None
    if symbolic is not None:
        with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="unsafe"):
            source_ledger.read_source_ledger(symbolic, root=tmp_path)

    hard = tmp_path / "hard.json"
    try:
        os.link(target, hard)
    except OSError:
        hard = None
    if hard is not None:
        with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="unsafe"):
            source_ledger.read_source_ledger(hard, root=tmp_path)


def test_source_ledger_serializes_cross_process_merges(tmp_path: Path) -> None:
    path = tmp_path / "extracted_sources.json"
    script = "\n".join(
        [
            "import sys",
            "from pathlib import Path",
            "from distill.library.source_ledger import merge_source_ledger",
            "path = Path(sys.argv[1])",
            "root = Path(sys.argv[2])",
            "worker = int(sys.argv[3])",
            "for index in range(20):",
            "    merge_source_ledger(path, [f'{worker}:{index}'], root=root)",
        ]
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path), str(tmp_path), str(worker)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for worker in range(4)
    ]

    failures: list[str] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode:
            failures.append(f"exit={process.returncode} stdout={stdout!r} stderr={stderr!r}")

    assert failures == []
    assert source_ledger.read_source_ledger(path, root=tmp_path) == {
        f"{worker}:{index}" for worker in range(4) for index in range(20)
    }


def test_source_ledger_rejects_serialized_overflow_without_touching_existing_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "state" / "extracted_sources.json"
    source_ledger.merge_source_ledger(path, ["safe"], root=tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(source_ledger, "MAX_SOURCE_LEDGER_BYTES", len(before) + 8)

    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="serialized ledger"):
        source_ledger.merge_source_ledger(path, ["a-new-source-id"], root=tmp_path)

    assert path.read_bytes() == before


def test_source_ledger_rejects_linked_parent_at_primitive_boundary(tmp_path: Path) -> None:
    root = tmp_path / "topic"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    external_ledger = external / "extracted_sources.json"
    external_ledger.write_text('["outside"]', encoding="utf-8")
    linked_parent = root / ".claims"
    try:
        linked_parent.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    path = linked_parent / "extracted_sources.json"
    before = external_ledger.read_bytes()

    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="private directory"):
        source_ledger.read_source_ledger(path, root=root)
    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="private directory"):
        source_ledger.merge_source_ledger(path, ["new"], root=root)

    assert external_ledger.read_bytes() == before


def test_source_ledger_detects_parent_swap_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "topic"
    root.mkdir()
    state_dir = root / ".claims"
    path = state_dir / "extracted_sources.json"
    source_ledger.merge_source_ledger(path, ["safe"], root=root)
    original_bytes = path.read_bytes()
    external = tmp_path / "external"
    external.mkdir()
    external_ledger = external / "extracted_sources.json"
    external_ledger.write_text('["outside"]', encoding="utf-8")
    external_bytes = external_ledger.read_bytes()
    probe = root / "symlink-probe"
    try:
        probe.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    probe.unlink()
    preserved = root / ".claims-preserved"
    real_write = source_ledger.atomic_write_confined_bytes

    def swapping_write(
        target: Path,
        content: bytes,
        confinement_root: Path,
        *,
        exclusive: bool = False,
    ) -> None:
        state_dir.rename(preserved)
        state_dir.symlink_to(external, target_is_directory=True)
        real_write(
            target,
            content,
            confinement_root,
            exclusive=exclusive,
        )

    monkeypatch.setattr(source_ledger, "atomic_write_confined_bytes", swapping_write)

    with pytest.raises(source_ledger.SourceLedgerIntegrityError, match="private directory"):
        source_ledger.merge_source_ledger(path, ["new"], root=root)

    assert (preserved / "extracted_sources.json").read_bytes() == original_bytes
    assert external_ledger.read_bytes() == external_bytes
