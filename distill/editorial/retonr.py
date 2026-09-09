"""Optional adapter to Retonr's implemented candidate-check CLI."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from distill.library.paths import atomic_write_json
from distill.parsing import strict_json_loads


def check_revision(executable: Path, original: Path, candidate: Path, report: Path) -> None:
    """Check plain-text candidate fidelity without claiming Retonr can rewrite.

    The process receives no provider credentials. Markdown is treated as text;
    our own format and citation checks still run after this optional check.
    """
    executable = executable.resolve(strict=True)
    if not executable.is_file() or executable.suffix.lower() in {".bat", ".cmd", ".ps1"}:
        raise ValueError("Retonr executable must be a native binary, not a shell script")
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE"}
    }
    # Explicit native executable, fixed argv, no shell.
    result = subprocess.run(  # nosec B603
        [
            str(executable),
            "check",
            str(original.resolve()),
            str(candidate.resolve()),
            "--format",
            "json",
            "--fail-on-abstain",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    payload = strict_json_loads(result.stdout.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Retonr returned an invalid report")
    atomic_write_json(report, payload)
    record = payload.get("result")
    if (
        result.returncode != 0
        or payload.get("schema_version") != 1
        or payload.get("command") != "check"
        or payload.get("status") != "ok"
        or not isinstance(record, dict)
        or record.get("schema_version") != 2
        or record.get("status") not in {"rewritten", "unchanged_no_eligible_content"}
    ):
        raise ValueError("Retonr did not accept this revision; see the saved check report")
    if (
        record.get("source_digest") != hashlib.sha256(original.read_bytes()).hexdigest()
        or record.get("output_digest") != hashlib.sha256(candidate.read_bytes()).hexdigest()
    ):
        raise ValueError("Retonr report does not match the supplied draft and candidate")
