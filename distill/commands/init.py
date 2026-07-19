# pyright: strict
"""``distill init`` -- guided, idempotent first-run setup.

Creates a ``.env`` (without ever clobbering an existing one), helps pick the
cloud or local provider, live-validates the key, ensures the Playwright browser
is present, and ends on a readiness verdict plus the first command to try.

Every prompt degrades safely with no TTY (loop/agent shells), so ``distill init``
never hangs unattended -- it falls back to creating the env file and printing the
manual next steps. Registered onto the app from ``distill.cli`` (mirroring
``update`` / ``audit``). Pure file helpers live at module top for testability.
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from collections.abc import Callable, Generator
from errno import ELOOP
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

import typer

from distill._console import console
from distill.commands._helpers import tty_confirm, tty_prompt
from distill.commands._json import emit_json, json_mode_active
from distill.library.locking import exclusive_file_lock, open_lock_file
from distill.library.paths import atomic_write_text

type InitProvider = Literal["cloud", "local"]


class InitState(TypedDict):
    env_file: str
    env_created: bool
    provider: InitProvider
    xai_key: str
    local: str
    browser: str
    ready: bool
    next: str
    blocking: list[str]
    local_reachable: NotRequired[bool]


__all__ = ["init_cmd", "register"]

# Built-in template so `init` works for pip/uvx installs where the repo's
# `.env.example` isn't on disk. Keys first (the thing users actually set);
# advanced overrides are documented in `.env.example` / docs, not duplicated.
_ENV_TEMPLATE = """\
# Distill configuration -- created by `distill init`.
# Cloud (default): set XAI_API_KEY. Get one at https://console.x.ai/
XAI_API_KEY=

# Optional: Gemini Deep Research for `distill research-brief` (https://aistudio.google.com/apikey)
GEMINI_API_KEY=

# Local inference instead of cloud (no key needed): uncomment one.
# DISTILL_PROVIDER=ollama
# DISTILL_PROVIDER=lmstudio
# OLLAMA_BASE_URL=http://localhost:11434

# Optional: where the corpus lives (default: ~/.distill/library)
# DISTILL_OUTPUT_DIR=./library
"""


def _env_file_operation[T](path: Path, operation: Callable[[], T]) -> T:
    """Run one expected env-file operation with a stable CLI failure surface."""

    try:
        return operation()
    except (OSError, ValueError) as exc:
        message = f"Environment configuration failed for {path}: {exc}"
        if json_mode_active():
            emit_json(
                {"reason": "env_file_error", "env_file": str(path)},
                error=message,
            )
        else:
            console.print(f"[red]{message}[/red]")
        exit_code = 3 if isinstance(exc, ValueError) else 1
        raise typer.Exit(exit_code) from exc


_ENV_FILE_MODE = 0o600
_POSIX_PERMISSIONS = os.name == "posix"
_ENV_RACE_RETRIES = 3
_ENV_LOCK_TIMEOUT_SECONDS = 10.0


def env_file_path() -> Path:
    """The ``.env`` distill loads -- the one in the current working directory
    (Pydantic Settings reads ``.env`` relative to cwd)."""
    return Path.cwd() / ".env"


def _initial_env_stat(path: Path) -> os.stat_result | None:
    """Return validated initial metadata for an existing regular env file."""
    try:
        initial_stat = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(initial_stat.st_mode):
        raise ValueError(f"Refusing to use a symbolic link as an env file: {path}")
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ValueError(f"Refusing to use a non-file env path: {path}")
    if initial_stat.st_nlink != 1:
        raise ValueError(f"Refusing to use a multiply linked env file: {path}")
    return initial_stat


def _validate_env_descriptor(
    path: Path,
    descriptor: int,
    initial_stat: os.stat_result,
) -> None:
    """Confirm the opened descriptor still identifies the validated path."""
    descriptor_stat = os.fstat(descriptor)
    path_stat = path.lstat()
    if stat.S_ISLNK(path_stat.st_mode):
        raise ValueError(f"Refusing to use a symbolic link as an env file: {path}")
    if not stat.S_ISREG(descriptor_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise ValueError(f"Refusing to use a non-file env path: {path}")
    if descriptor_stat.st_nlink != 1 or path_stat.st_nlink != 1:
        raise ValueError(f"Refusing to use a multiply linked env file: {path}")
    identities = {
        (initial_stat.st_dev, initial_stat.st_ino),
        (descriptor_stat.st_dev, descriptor_stat.st_ino),
        (path_stat.st_dev, path_stat.st_ino),
    }
    if len(identities) != 1:
        raise ValueError(f"Env file changed while it was being opened: {path}")


def _open_existing_env(path: Path) -> int | None:
    """Open an existing regular env file by descriptor, never through a symlink."""

    initial_stat = _initial_env_stat(path)
    if initial_stat is None:
        return None
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == ELOOP:
            raise ValueError(f"Refusing to use a symbolic link as an env file: {path}") from exc
        raise
    try:
        _validate_env_descriptor(path, descriptor, initial_stat)
        if _POSIX_PERMISSIONS:
            os.fchmod(descriptor, _ENV_FILE_MODE)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_existing_env(path: Path) -> str | None:
    """Read an existing env file through the validated descriptor."""

    descriptor = _open_existing_env(path)
    if descriptor is None:
        return None
    with os.fdopen(descriptor, encoding="utf-8") as env_file:
        return env_file.read()


def _validate_env_path(path: Path) -> None:
    """Reject paths whose writes could affect a different filesystem object."""

    if path.is_symlink():
        raise ValueError(f"Refusing to use a symbolic link as an env file: {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"Refusing to use a non-file env path: {path}")


def _write_env_text(path: Path, content: str) -> None:
    """Atomically write env content with owner-only POSIX permissions."""
    _validate_env_path(path)
    atomic_write_text(path, content)


def _create_env_text_exclusive(path: Path, content: str) -> bool:
    """Publish a complete env file only when no directory entry already exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        try:
            env_file = os.fdopen(descriptor, "w", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            raise
        with env_file:
            env_file.write(content)
            env_file.flush()
            os.fsync(env_file.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError:
            return False
        return True
    finally:
        temp_path.unlink(missing_ok=True)


def _create_env_if_absent(path: Path, content: str) -> bool:
    """Create once or preserve a concurrently published regular env file."""

    for _ in range(_ENV_RACE_RETRIES):
        descriptor = _open_existing_env(path)
        if descriptor is not None:
            os.close(descriptor)
            return False
        if _create_env_text_exclusive(path, content):
            return True
    raise OSError(f"Env path changed repeatedly while it was being created: {path}")


@contextlib.contextmanager
def _env_update_lock(path: Path) -> Generator[None]:
    """Serialize env read-modify-write operations across threads and processes."""

    lock_path = path.with_name(f"{path.name}.distill.lock")
    with (
        open_lock_file(lock_path) as lock_file,
        exclusive_file_lock(
            lock_file,
            timeout_seconds=_ENV_LOCK_TIMEOUT_SECONDS,
            timeout_message=f"timed out waiting for the env lock: {path}",
        ),
    ):
        yield


def create_env_file(path: Path, *, force: bool = False) -> bool:
    """Write the env template to *path*. Returns True if it created/overwrote a
    file, False if one already existed and *force* was not set.

    Never clobbers an existing ``.env`` unless *force* -- that file holds the
    user's API keys, and silently overwriting it is the one failure mode this
    command must not have.
    """
    with _env_update_lock(path):
        _validate_env_path(path)
        if force:
            _write_env_text(path, _ENV_TEMPLATE)
            return True
        return _create_env_if_absent(path, _ENV_TEMPLATE)


def set_env_var(path: Path, key: str, value: str) -> None:
    """Set ``key=value`` in the env file, preserving every other line.

    Replaces an existing ``key=...`` line in place (comment lines like
    ``# key=`` are left untouched); appends the assignment if absent. Creates the
    file from the template first if it does not exist.
    """
    with _env_update_lock(path):
        _validate_env_path(path)
        existing: str | None = None
        for _ in range(_ENV_RACE_RETRIES):
            existing = _read_existing_env(path)
            if existing is not None:
                break
            if _create_env_text_exclusive(path, _ENV_TEMPLATE):
                existing = _ENV_TEMPLATE
                break
        if existing is None:
            raise OSError(f"Env path changed repeatedly while it was being opened: {path}")
        lines = existing.splitlines()
        prefix = f"{key}="
        replaced = False
        for i, line in enumerate(lines):
            if line.lstrip().startswith(prefix) and not line.lstrip().startswith("#"):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")
        _write_env_text(path, "\n".join(lines) + "\n")


def chromium_status() -> str:
    """Whether the Playwright Chromium build is installed.

    Returns ``"installed"``, ``"missing"``, ``"unsafe"``, or ``"unknown"``.
    Checks the expected executable path rather than launching a browser, so it
    is cheap and side-effect-free.
    """
    from distill.process_security import unsafe_package_overrides

    if unsafe_package_overrides():
        return "unsafe"
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return "unknown"
    try:
        with sync_playwright() as p:
            exe = p.chromium.executable_path
        return "installed" if exe and Path(exe).exists() else "missing"
    except Exception:
        return "missing"


def _install_chromium() -> bool:
    """Run ``playwright install chromium`` with a hardened subprocess env (same
    discipline as the yt-dlp updater: no PYTHONPATH/PYTHONHOME injection).
    Returns True on success."""
    import subprocess
    import sys

    from distill.process_security import package_install_context

    cwd, env = package_install_context()
    try:
        result = subprocess.run(
            [sys.executable, "-P", "-m", "playwright", "install", "chromium"],
            cwd=cwd,
            env=env,
            check=False,
        )
        return result.returncode == 0
    except Exception as e:
        console.print(f"  [red]Browser install failed:[/red] {e}")
        return False


def _validate_xai() -> tuple[str, str]:
    """Live-validate the XAI key via the canonical doctor checker (so init and
    doctor can't drift). Lazy import keeps init load-light."""
    from distill.commands._helpers import get_config
    from distill.doctor.checks import doctor_validate_key

    return doctor_validate_key("xai", get_config())


_KEY_LABEL = {
    "ok": "[green]valid[/green]",
    "invalid": "[red]rejected by xAI (revoked/expired key?)[/red]",
    "missing": "[yellow]not set[/yellow]",
    "unknown": "[yellow]could not verify (offline?)[/yellow]",
    "skipped": "[yellow]live validation skipped by no-metered policy[/yellow]",
}


def _emit_verdict(state: InitState) -> None:
    if json_mode_active():
        emit_json(state)
        return
    console.print()
    icon = "[green]ready[/green]" if state["ready"] else "[yellow]not ready yet[/yellow]"
    console.print(f"  Setup: {icon}")
    if state["provider"] == "cloud":
        console.print(f"  xAI key: {_KEY_LABEL.get(state['xai_key'], state['xai_key'])}")
    else:
        console.print(f"  Local provider: {state['provider']}  ({state['local']})")
    console.print(f"  Browser: {state['browser']}")
    console.print()
    if state["ready"]:
        console.print(f"  [bold]Try it:[/bold]  {state['next']}", soft_wrap=True)
    else:
        for hint in state["blocking"]:
            console.print(f"  [dim]- {hint}[/dim]")


def _local_provider() -> str:
    """The configured local provider name from the environment (after .env is
    loaded), or empty if the provider is still cloud."""
    import os

    name = os.environ.get("DISTILL_PROVIDER", "").strip().lower()
    return name if name in ("ollama", "lmstudio") else ""


def _local_reachable(provider: str) -> str:
    """Lightweight reachability probe for the local provider. Returns
    'reachable' or 'unreachable'. Reads the same base-URL env vars the
    providers themselves honor (OLLAMA_BASE_URL / LMSTUDIO_BASE_URL)."""
    import os

    import httpx

    if provider == "ollama":
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        probe = base.rstrip("/") + "/api/tags"
    else:
        base = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
        probe = base.rstrip("/") + "/models"
    try:
        with httpx.stream("GET", probe, timeout=2.0) as response:
            return "reachable" if response.status_code < 500 else "unreachable"
    except Exception:
        return "unreachable"


def init_cmd(  # noqa: C901 -- guided wizard; branchy by nature, each branch is flat
    provider: str | None = typer.Option(
        None, "--provider", help="cloud | local -- skip the prompt and pick directly"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Non-interactive: accept defaults, don't prompt"
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing .env (default: never clobber)"
    ),
    install_browser: bool = typer.Option(
        True, "--browser/--no-browser", help="Install Playwright Chromium if missing"
    ),
) -> None:
    """Set up Distill and ready a browser.

    Cloud key validation is live and may be billed. Pass the global
    ``--cost-mode no-metered`` option to refuse API-billed or ambiguous probes.
    """
    quiet = json_mode_active()
    env_path = env_file_path()

    # 1. Env file -- create if missing, never clobber without --force.
    created = _env_file_operation(env_path, lambda: create_env_file(env_path, force=force))
    if not quiet:
        if created:
            console.print(f"  [green]Created[/green] {env_path}")
        else:
            console.print(f"  [dim]Found existing[/dim] {env_path} [dim](kept as-is)[/dim]")

    # 2. Provider choice (cloud is the default; honor an explicit flag or --yes).
    if provider in ("cloud", "local"):
        choice: InitProvider = "local" if provider == "local" else "cloud"
    elif yes:
        choice = "cloud"
    else:
        prompt_choice = (
            tty_prompt(
                "Provider -- cloud (xAI) or local (ollama/lmstudio)?",
                default="cloud",
                non_tty_default="cloud",
            )
            .strip()
            .lower()
        )
        choice = "local" if prompt_choice.startswith("l") else "cloud"

    state: InitState = {
        "env_file": str(env_path),
        "env_created": created,
        "provider": choice,
        "xai_key": "missing",
        "local": "",
        "browser": "unknown",
        "ready": False,
        "next": "",
        "blocking": [],
    }

    # 3. Provider-specific setup.
    if choice == "cloud":
        # Offer to capture a key interactively; under --yes / no-TTY we don't
        # prompt, so we leave the template value and tell the user where to set it.
        if not yes:
            entered = tty_prompt(
                "Paste your XAI_API_KEY (blank to skip and set it later)",
                default="",
                non_tty_default="",
            ).strip()
            if entered:
                _env_file_operation(
                    env_path,
                    lambda: set_env_var(env_path, "XAI_API_KEY", entered),
                )
                if not quiet:
                    console.print("  [green]Saved[/green] XAI_API_KEY to .env")
        if not quiet:
            console.print("  Validating key against xAI ...")
        status, _detail = _validate_xai()
        state["xai_key"] = status
        if status == "skipped":
            state["blocking"].append(
                "Cloud key validation is blocked by DISTILL_COST_MODE=no-metered. "
                "Choose a local provider, or explicitly use paid-ok before validating a cloud key."
            )
        elif status != "ok":
            state["blocking"].append(
                "Set a valid XAI_API_KEY in .env (get one at https://console.x.ai/), "
                "then re-run `distill init` or `distill doctor`."
            )
    else:
        from distill.commands._helpers import get_config

        get_config()  # side effect: load_dotenv so DISTILL_PROVIDER is in os.environ
        prov = _local_provider()
        if not prov:
            # User asked for local but .env still defaults to cloud -- set it.
            _env_file_operation(
                env_path,
                lambda: set_env_var(env_path, "DISTILL_PROVIDER", "ollama"),
            )
            prov = "ollama"
            if not quiet:
                console.print("  [green]Set[/green] DISTILL_PROVIDER=ollama in .env")
        reach = _local_reachable(prov)
        state["provider"] = "local"
        state["local"] = f"{prov}: {reach}"
        state["local_reachable"] = reach == "reachable"
        if reach != "reachable":
            if prov == "ollama":
                blocker = (
                    "Start Ollama and pull a model, e.g. `ollama pull qwen3.5:27b`, "
                    "then re-run `distill init`."
                )
            else:
                blocker = "Start LM Studio and load a model, then re-run `distill init`."
            state["blocking"].append(blocker)

    # 4. Browser -- the #1 silent ingest failure if absent.
    browser = chromium_status()
    if browser == "missing" and install_browser:
        do_install = yes or tty_confirm(
            "Playwright Chromium is missing -- install it now (~150MB)?", default=False
        )
        if do_install:
            if not quiet:
                console.print("  Installing Chromium ...")
            browser = "installed" if _install_chromium() else "missing"
    state["browser"] = browser
    if browser == "unsafe":
        from distill.process_security import unsafe_package_overrides

        names = ", ".join(unsafe_package_overrides())
        state["blocking"].append(f"Remove unsafe browser execution environment variables: {names}.")
    elif browser != "installed":
        state["blocking"].append("Run `playwright install chromium` for YouTube + web capture.")

    # 5. Readiness verdict + first command.
    if choice == "cloud":
        state["ready"] = state["xai_key"] == "ok" and state["browser"] == "installed"
    else:
        state["ready"] = state.get("local_reachable", False) and state["browser"] == "installed"
    next_cost_mode = "paid-ok" if choice == "cloud" else "no-metered"
    state["next"] = (
        f'distill --cost-mode {next_cost_mode} papers "agent memory systems" '
        "--topic memory --preview"
    )
    _emit_verdict(state)
    if not state["ready"]:
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Attach the ``init`` command to the app (called from distill.cli)."""
    app.command(name="init", rich_help_panel="Maintain")(init_cmd)
