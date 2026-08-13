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
import re
import stat
import tempfile
from collections.abc import Callable, Generator
from errno import ELOOP
from io import StringIO
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

import typer
from dotenv import dotenv_values
from rich.markup import escape

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
    analysis_provider: NotRequired[str]
    analysis_model: NotRequired[str]
    local_reachable: NotRequired[bool]
    local_model: NotRequired[str]
    local_model_ready: NotRequired[bool]
    local_models: NotRequired[list[str]]


__all__ = ["init_cmd", "register"]

# Built-in template so `init` works for pip/uvx installs where the repo's
# `.env.example` isn't on disk. Keys first (the thing users actually set);
# advanced overrides are documented in `.env.example` / docs, not duplicated.
_ENV_TEMPLATE = """\
# Distill configuration -- created by `distill init`.
# Cloud (default): set XAI_API_KEY. Get one at https://console.x.ai/
XAI_API_KEY=

# Optional Gemini analysis route and Deep Research reports
# (https://aistudio.google.com/apikey). After init defaults to xAI, switch with:
#   distill provider set gemini gemini-3.6-flash
GEMINI_API_KEY=

# Local inference instead of cloud (no key needed): uncomment one, or run
#   distill provider set ollama qwen3.5:27b
# DISTILL_PROVIDER=ollama
# DISTILL_PROVIDER=lmstudio
# DISTILL_MODEL=qwen3.5:27b
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
_ENV_KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")


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


def _render_env_assignment(key: str, value: str) -> str:
    """Render one ``key=value`` line that reads back byte-identical.

    Values were written bare, so python-dotenv reinterpreted them on read: a
    ``#`` started a comment (silently truncating the value) and surrounding
    whitespace was stripped. Quote only the values that need it, so ordinary keys
    and model ids keep the plain, human-editable ``KEY=value`` form and only the
    ambiguous cases gain quotes. ``${...}`` is rejected in ``set_env_var``
    because no quoting or escaping suppresses dotenv's interpolation.
    """
    if value and value == value.strip() and not any(c in value for c in "#\"\\'"):
        return f"{key}={value}"
    if not value:
        return f"{key}="
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{key}="{escaped}"'


def _updated_env_content(existing: str, key: str, value: str) -> str:
    """Return env content with exactly one active assignment for ``key``."""

    assignment = re.compile(rf"^(?:export[ \t]+)?{re.escape(key)}[ \t]*=")
    replaced = False
    updated: list[str] = []
    rendered = _render_env_assignment(key, value)
    for line in existing.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("#") and assignment.match(stripped):
            if not replaced:
                updated.append(rendered)
            replaced = True
            continue
        updated.append(line)
    if not replaced:
        updated.append(rendered)
    return "\n".join(updated) + "\n"


def set_env_var(path: Path, key: str, value: str) -> None:
    """Set ``key=value`` in the env file, preserving every other line.

    Replaces an existing ``key=...`` line in place (comment lines like
    ``# key=`` are left untouched); appends the assignment if absent. Creates the
    file from the template first if it does not exist.
    """
    if not _ENV_KEY_PATTERN.fullmatch(key):
        raise ValueError("Environment variable name is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Environment variable value contains control characters")
    # python-dotenv interpolates ``${...}`` on read even inside quotes, and a
    # backslash does not escape it, so such a value cannot round-trip: a pasted
    # secret containing "${" came back with an environment value spliced into it.
    # Refusing is the only safe option -- silently corrupting a key is worse than
    # a clear error.
    if "${" in value:
        raise ValueError(
            "Environment variable value cannot contain '${': it would be substituted "
            "when the env file is read back"
        )

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
        _write_env_text(path, _updated_env_content(existing, key, value))


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


def _validate_xai(model: str = "") -> tuple[str, str]:
    """Live-validate the XAI key via the canonical doctor checker (so init and
    doctor can't drift). Lazy import keeps init load-light."""
    from distill.commands._helpers import get_config
    from distill.doctor.checks import doctor_validate_key

    config = get_config()
    if model:
        config = config.model_copy(update={"xai_analysis_model": model})
    return doctor_validate_key("xai", config)


_KEY_LABEL = {
    "ok": "[green]valid[/green]",
    "invalid": "[red]rejected by xAI (revoked/expired key?)[/red]",
    "missing": "[yellow]not set[/yellow]",
    "unknown": "[yellow]could not verify (offline?)[/yellow]",
    "skipped": "[yellow]live validation skipped by no-metered policy[/yellow]",
    "not-checked": "[yellow]not checked until routing is resolved[/yellow]",
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
        console.print(f"  Local provider: {escape(state['local'])}")
        if local_model := state.get("local_model", ""):
            model_status = "loaded" if state.get("local_model_ready", False) else "not loaded"
            console.print(f"  Local model: {escape(local_model)} ({model_status})")
    analysis_provider = str(state.get("analysis_provider", "") or "")
    analysis_model = str(state.get("analysis_model", "") or "")
    if analysis_provider and analysis_model:
        console.print(f"  Analysis route: {escape(analysis_provider)} / {escape(analysis_model)}")
    console.print(f"  Browser: {state['browser']}")
    console.print()
    if state["ready"]:
        console.print(f"  [bold]Try it:[/bold]  {escape(state['next'])}", soft_wrap=True)
        if state["provider"] == "cloud":
            console.print(
                "  [dim]Other analysis routes:[/dim]  "
                "distill provider list   |   "
                "distill provider set gemini gemini-3.6-flash"
            )
    else:
        for hint in state["blocking"]:
            console.print(f"  [dim]- {escape(hint)}[/dim]")


def _local_provider() -> str:
    """The configured local provider name from the environment (after .env is
    loaded), or empty if the provider is still cloud."""
    import os

    name = os.environ.get("DISTILL_PROVIDER", "").strip().lower()
    return name if name in ("ollama", "lmstudio") else ""


def _local_model_inventory(provider: str) -> tuple[str, list[str]]:
    """Return provider status and exact model ids through bounded doctor probes."""
    from distill.doctor.checks import check_lmstudio_models, check_ollama_status

    if provider == "ollama":
        return check_ollama_status()
    return check_lmstudio_models()


def _has_any_model_override() -> bool:
    """Return whether the operator configured any router model field."""
    from distill.llm.router import RouterConfig

    return any(
        os.environ.get(f"DISTILL_{field_name.upper()}", "").strip()
        for field_name in RouterConfig.model_fields
        if field_name == "model" or field_name.endswith("_model")
    )


def _is_xai_text_model(model: str) -> bool:
    """Return whether a resolved model belongs to xAI's text-model namespace."""

    from distill.llm.model_policy import is_xai_media_generation_model

    normalized = model.strip().lower()
    return normalized.startswith("grok-") and not is_xai_media_generation_model(normalized)


def _env_file_value(content: str, name: str) -> str:
    """Read one assignment from validated env-file content."""

    value = dotenv_values(stream=StringIO(content), interpolate=False).get(name)
    return value.strip() if isinstance(value, str) else ""


def _env_assignment(content: str, name: str) -> str:
    """Read one normalized routing assignment from env-file content."""

    return _env_file_value(content, name).lower()


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    mapping = cast(dict[object, object], value)
    return {
        key: item for key, item in mapping.items() if isinstance(key, str) and isinstance(item, str)
    }


def _string_tuple_set(value: object) -> set[str]:
    if not isinstance(value, tuple):
        return set()
    return {item for item in cast(tuple[object, ...], value) if isinstance(item, str)}


def _discard_overwritten_dotenv_values(
    content: str,
    *,
    preserved_names: set[str],
) -> None:
    """Remove process values loaded only from an env file replaced by ``--force``."""

    assignments = dotenv_values(stream=StringIO(content), interpolate=False)
    for name in assignments:
        if name not in preserved_names:
            os.environ.pop(name, None)


def init_cmd(  # noqa: C901 -- guided wizard; branchy by nature, each branch is flat
    ctx: typer.Context,
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="cloud (xAI analysis default) | local -- skip the prompt and pick directly",
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
    original_env = (
        _env_file_operation(
            env_path,
            lambda: _read_existing_env(env_path),
        )
        or ""
    )
    root_obj_raw: object = ctx.find_root().obj
    root_obj = cast(dict[str, object], root_obj_raw) if isinstance(root_obj_raw, dict) else {}
    initial_provider_environment = _string_mapping(root_obj.get("initial_provider_environment"))
    external_provider = (
        str(initial_provider_environment.get("DISTILL_PROVIDER", "")).strip().lower()
    )
    external_analysis_provider = (
        str(initial_provider_environment.get("DISTILL_ANALYSIS_PROVIDER", "")).strip().lower()
    )
    initial_xai_key = str(initial_provider_environment.get("XAI_API_KEY", "")).strip()

    # 1. Env file -- create if missing, never clobber without --force.
    created = _env_file_operation(env_path, lambda: create_env_file(env_path, force=force))
    retained_env = original_env
    if force and created:
        preserved_names = _string_tuple_set(root_obj.get("pre_dotenv_environment_keys"))
        _discard_overwritten_dotenv_values(
            original_env,
            preserved_names=preserved_names,
        )
        retained_env = ""
    persisted_analysis_provider = _env_assignment(
        retained_env,
        "DISTILL_ANALYSIS_PROVIDER",
    )
    persisted_xai_key = _env_file_value(retained_env, "XAI_API_KEY")
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
    cloud_route_ready = False

    # 3. Provider-specific setup.
    if choice == "cloud":
        _env_file_operation(
            env_path,
            lambda: set_env_var(env_path, "DISTILL_PROVIDER", "xai"),
        )
        os.environ["DISTILL_PROVIDER"] = "xai"
        # Offer to capture a key interactively; under --yes / no-TTY we don't
        # prompt, so we leave the template value and tell the user where to set it.
        entered = ""
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
                os.environ["XAI_API_KEY"] = entered
                if not quiet:
                    console.print("  [green]Saved[/green] XAI_API_KEY to .env")
        from distill.llm.router import RouterConfig

        cloud_provider, cloud_model = RouterConfig(provider="xai").resolve("analysis")
        shell_route_conflict = bool(
            (external_analysis_provider and external_analysis_provider != "xai")
            or (
                not external_analysis_provider
                and persisted_analysis_provider != "xai"
                and external_provider
                and external_provider != "xai"
            )
        )
        intended_xai_key = entered or persisted_xai_key
        shell_key_conflict = bool(
            initial_xai_key and intended_xai_key and initial_xai_key != intended_xai_key
        )
        if shell_key_conflict:
            state["xai_key"] = "not-checked"
            state["blocking"].append(
                "A shell-level XAI_API_KEY overrides the key saved in .env. Unset or "
                "update the shell variable, then re-run `distill init`."
            )
        elif shell_route_conflict:
            state["xai_key"] = "not-checked"
            state["blocking"].append(
                "A shell-level DISTILL_PROVIDER or DISTILL_ANALYSIS_PROVIDER overrides "
                "the xAI route saved in .env. Unset the conflicting shell variable, "
                "then re-run `distill init`."
            )
        elif cloud_provider != "xai":
            state["xai_key"] = "not-checked"
            state["blocking"].append(
                f"Configured analysis route '{cloud_provider}' overrides the selected xAI "
                "route. Remove DISTILL_ANALYSIS_PROVIDER or set it to xai, then re-run "
                "`distill init`."
            )
        elif not _is_xai_text_model(cloud_model):
            state["xai_key"] = "not-checked"
            state["blocking"].append(
                f"Configured analysis model '{cloud_model}' is not an xAI text model. "
                "Remove the stale DISTILL_MODEL or DISTILL_ANALYSIS_MODEL override, "
                "or set it to grok-4.6, then re-run `distill init`."
            )
        else:
            if not quiet:
                console.print("  Validating key against xAI ...")
            status, validated_model = _validate_xai(cloud_model)
            state["xai_key"] = status
            if status == "skipped":
                state["blocking"].append(
                    "Cloud key validation is blocked by DISTILL_COST_MODE=no-metered. "
                    "Choose a local provider, or explicitly use paid-ok before validating "
                    "a cloud key."
                )
            elif status != "ok":
                state["blocking"].append(
                    "Set a valid XAI_API_KEY in .env (get one at https://console.x.ai/), "
                    "then re-run `distill init` or `distill doctor`."
                )
            cloud_route_ready = status == "ok" and validated_model == cloud_model
            if status == "ok" and validated_model != cloud_model:
                state["blocking"].append(
                    "xAI validation did not confirm the exact configured analysis model. "
                    "Set DISTILL_MODEL or DISTILL_ANALYSIS_MODEL to the validated model, "
                    "then re-run `distill init`."
                )
    else:
        from distill.commands._helpers import get_config
        from distill.llm.cost_policy import blocked_route_message, evaluate_route_cost_policy

        runtime_config = get_config()
        analysis_provider = os.environ.get("DISTILL_ANALYSIS_PROVIDER", "").strip().lower()
        prov = analysis_provider if analysis_provider in {"ollama", "lmstudio"} else ""
        if not prov:
            prov = _local_provider() or "ollama"
        if persisted_analysis_provider not in {"ollama", "lmstudio"}:
            _env_file_operation(
                env_path,
                lambda: set_env_var(env_path, "DISTILL_PROVIDER", prov),
            )
            # Mirror into the process env like the cloud branch does. get_config()
            # already loaded the pre-existing .env into os.environ, and process env
            # outranks env_file, so without this the readiness verdict re-read the
            # stale provider and reported an impossible pair (e.g. "xai /
            # qwen3.5:27b") alongside ready: true.
            os.environ["DISTILL_PROVIDER"] = prov
            if not quiet:
                console.print(f"  [green]Set[/green] DISTILL_PROVIDER={prov} in .env")

        from distill.llm.router import RouterConfig

        route_config = RouterConfig(
            provider=prov,
            cost_mode=runtime_config.distill_cost_mode,
            xai_api_key=runtime_config.xai_api_key.get_secret_value(),
            gemini_api_key=runtime_config.gemini_api_key.get_secret_value(),
            anthropic_api_key=runtime_config.anthropic_api_key.get_secret_value(),
            openai_api_key=runtime_config.openai_api_key.get_secret_value(),
        )
        route_provider, resolved_model = route_config.resolve("analysis")
        configured_model = (
            resolved_model if route_config.has_explicit_local_model("analysis") else ""
        )
        route_decision = evaluate_route_cost_policy(
            cost_mode=runtime_config.distill_cost_mode,
            provider=route_provider,
            workload="init",
        )
        route_is_local = route_provider in {"ollama", "lmstudio"}
        persisted_local_analysis = persisted_analysis_provider in {"ollama", "lmstudio"}
        shell_route_conflict = bool(
            (external_analysis_provider and external_analysis_provider != prov)
            or (
                not external_analysis_provider
                and not persisted_local_analysis
                and external_provider
                and external_provider != prov
            )
        )
        route_allowed = (
            route_is_local and route_decision.cost_class == "local" and not shell_route_conflict
        )
        state["provider"] = "local"
        state["local_model"] = configured_model
        state["local_model_ready"] = False
        state["local_models"] = []

        if not route_allowed:
            state["local"] = f"{route_provider}: blocked"
            state["local_reachable"] = False
            if shell_route_conflict:
                state["blocking"].append(
                    "A shell-level DISTILL_PROVIDER or DISTILL_ANALYSIS_PROVIDER overrides "
                    "the local route saved in .env. Unset the conflicting shell variable, "
                    "then re-run `distill init`."
                )
            elif not route_is_local:
                state["blocking"].append(
                    f"Configured analysis route '{route_provider}' is not local. Remove "
                    "DISTILL_ANALYSIS_PROVIDER or set it to ollama or lmstudio, then "
                    "re-run `distill init`."
                )
            elif not route_decision.allowed:
                state["blocking"].append(blocked_route_message(route_decision))
            else:
                state["blocking"].append(
                    f"Configured {route_provider} endpoint is not proven loopback. "
                    "Local setup only probes local inference. Restore its loopback endpoint, "
                    "then re-run `distill init`."
                )
        else:
            if (
                not configured_model
                and not _has_any_model_override()
                and route_provider == "ollama"
            ):
                configured_model = "qwen3.5:27b"
                _env_file_operation(
                    env_path,
                    lambda: set_env_var(env_path, "DISTILL_MODEL", configured_model),
                )
                # Mirror so the readiness verdict below resolves the model that was
                # just written rather than a stale process-env value.
                os.environ["DISTILL_MODEL"] = configured_model
                state["local_model"] = configured_model
                if not quiet:
                    console.print(f"  [green]Set[/green] DISTILL_MODEL={configured_model} in .env")

            local_status, local_models = _local_model_inventory(route_provider)
            state["local"] = f"{route_provider}: {local_status}"
            state["local_reachable"] = local_status == "running"
            state["local_models"] = local_models
            model_ready = bool(configured_model) and configured_model in local_models
            state["local_model_ready"] = model_ready

        if route_allowed and not state["local_reachable"]:
            if route_provider == "ollama":
                blocker = (
                    "Start Ollama and pull a model, e.g. `ollama pull qwen3.5:27b`, "
                    "then re-run `distill init`."
                )
            else:
                blocker = "Start LM Studio and load a model, then re-run `distill init`."
            state["blocking"].append(blocker)
        elif route_allowed and not configured_model:
            available = state["local_models"]
            example = f", for example '{available[0]}'" if available else ""
            state["blocking"].append(
                f"Set DISTILL_MODEL or DISTILL_ANALYSIS_MODEL to an exact loaded "
                f"{route_provider} model id{example}, "
                "then re-run `distill init`."
            )
        elif route_allowed and not state["local_model_ready"]:
            if route_provider == "ollama":
                state["blocking"].append(
                    f"Configured model '{configured_model}' is not installed in Ollama. "
                    f"Run `ollama pull {configured_model}`, then re-run `distill init`."
                )
            else:
                state["blocking"].append(
                    f"Configured model '{configured_model}' is not loaded in LM Studio. "
                    "Load that exact model, then re-run `distill init`."
                )

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
        state["ready"] = cloud_route_ready and state["browser"] == "installed"
    else:
        state["ready"] = (
            state.get("local_reachable", False)
            and state.get("local_model_ready", False)
            and state["browser"] == "installed"
        )
    next_cost_mode = "paid-ok" if choice == "cloud" else "no-metered"
    state["next"] = (
        f'distill --cost-mode {next_cost_mode} papers "agent memory systems" '
        "--topic memory --preview"
    )
    try:
        from distill.llm.router import RouterConfig

        route_provider, route_model = RouterConfig().resolve("analysis")
        state["analysis_provider"] = route_provider
        state["analysis_model"] = route_model
    except Exception:
        # Setup verdict remains useful even if route resolution is incomplete.
        pass
    _emit_verdict(state)
    if not state["ready"]:
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Attach the ``init`` command to the app (called from distill.cli)."""
    app.command(name="init", rich_help_panel="Maintain")(init_cmd)
