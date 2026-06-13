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

from pathlib import Path

import typer

from distill._console import console
from distill.commands._helpers import tty_confirm, tty_prompt
from distill.commands._json import emit_json, json_mode_active

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


def env_file_path() -> Path:
    """The ``.env`` distill loads -- the one in the current working directory
    (Pydantic Settings reads ``.env`` relative to cwd)."""
    return Path.cwd() / ".env"


def create_env_file(path: Path, *, force: bool = False) -> bool:
    """Write the env template to *path*. Returns True if it created/overwrote a
    file, False if one already existed and *force* was not set.

    Never clobbers an existing ``.env`` unless *force* -- that file holds the
    user's API keys, and silently overwriting it is the one failure mode this
    command must not have.
    """
    if path.exists() and not force:
        return False
    path.write_text(_ENV_TEMPLATE, encoding="utf-8")
    return True


def set_env_var(path: Path, key: str, value: str) -> None:
    """Set ``key=value`` in the env file, preserving every other line.

    Replaces an existing ``key=...`` line in place (comment lines like
    ``# key=`` are left untouched); appends the assignment if absent. Creates the
    file from the template first if it does not exist.
    """
    if not path.exists():
        create_env_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    replaced = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(prefix) and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def chromium_status() -> str:
    """Whether the Playwright Chromium build is installed.

    Returns ``"installed"``, ``"missing"``, or ``"unknown"`` (Playwright itself
    not importable). Checks the expected executable path rather than launching a
    browser, so it is cheap and side-effect-free.
    """
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
    import os
    import subprocess
    import sys

    # Fixed argv from sys.executable, no shell, PYTHONPATH/PYTHONHOME stripped --
    # same hardening as the yt-dlp updater (bandit B404/B603 are LOW and clear).
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
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
    from distill.doctor.checks import _doctor_validate_key

    return _doctor_validate_key("xai", get_config())


_KEY_LABEL = {
    "ok": "[green]valid[/green]",
    "invalid": "[red]rejected by xAI (revoked/expired key?)[/red]",
    "missing": "[yellow]not set[/yellow]",
    "unknown": "[yellow]could not verify (offline?)[/yellow]",
}


def _emit_verdict(state: dict) -> None:
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
        console.print(f"  [bold]Try it:[/bold]  {state['next']}")
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
        resp = httpx.get(probe, timeout=2.0)
        return "reachable" if resp.status_code < 500 else "unreachable"
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
    """Set up distill: create .env, pick a provider, validate your key, ready a browser."""
    quiet = json_mode_active()
    env_path = env_file_path()

    # 1. Env file -- create if missing, never clobber without --force.
    created = create_env_file(env_path, force=force)
    if not quiet:
        if created:
            console.print(f"  [green]Created[/green] {env_path}")
        else:
            console.print(f"  [dim]Found existing[/dim] {env_path} [dim](kept as-is)[/dim]")

    # 2. Provider choice (cloud is the default; honor an explicit flag or --yes).
    if provider in ("cloud", "local"):
        choice = provider
    elif yes:
        choice = "cloud"
    else:
        choice = (
            tty_prompt(
                "Provider -- cloud (xAI) or local (ollama/lmstudio)?",
                default="cloud",
                non_tty_default="cloud",
            )
            .strip()
            .lower()
        )
        choice = "local" if choice.startswith("l") else "cloud"

    state: dict = {
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
        # prompt -- we leave the placeholder and tell the user where to set it.
        if not yes:
            entered = tty_prompt(
                "Paste your XAI_API_KEY (blank to skip and set it later)",
                default="",
                non_tty_default="",
            ).strip()
            if entered:
                set_env_var(env_path, "XAI_API_KEY", entered)
                if not quiet:
                    console.print("  [green]Saved[/green] XAI_API_KEY to .env")
        if not quiet:
            console.print("  Validating key against xAI ...")
        status, _detail = _validate_xai()
        state["xai_key"] = status
        if status != "ok":
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
            set_env_var(env_path, "DISTILL_PROVIDER", "ollama")
            prov = "ollama"
            if not quiet:
                console.print("  [green]Set[/green] DISTILL_PROVIDER=ollama in .env")
        reach = _local_reachable(prov)
        state["provider"] = "local"
        state["local"] = f"{prov}: {reach}"
        state["local_reachable"] = reach == "reachable"
        if reach != "reachable":
            state["blocking"].append(
                f"Start your local provider ({prov}) and pull a model, "
                "e.g. `ollama pull qwen3.5:27b`."
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
    if browser != "installed":
        state["blocking"].append("Run `playwright install chromium` for YouTube + web capture.")

    # 5. Readiness verdict + first command.
    if choice == "cloud":
        state["ready"] = state["xai_key"] == "ok" and state["browser"] == "installed"
    else:
        state["ready"] = state.get("local_reachable", False) and state["browser"] == "installed"
    state["next"] = 'distill papers "agent memory systems" --topic memory --preview'
    _emit_verdict(state)
    if not state["ready"]:
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Attach the ``init`` command to the app (called from distill.cli)."""
    app.command(name="init", rich_help_panel="Maintain")(init_cmd)
