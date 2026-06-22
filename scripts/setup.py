"""Distill setup -- one command to get everything running.

Works on Windows, macOS, and Linux.

Usage:
    python scripts/setup.py          First-time setup (install, keys, browser, verify)
    python scripts/setup.py --check  Re-validate everything without changing anything
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

# ── Display helpers ──────────────────────────────────────────────

# Safe characters for any terminal encoding (cp1252, utf-8, etc.)
try:
    "✓".encode(sys.stdout.encoding or "utf-8")
    _PASS, _FAIL, _WARN, _SKIP = "✓", "✗", "⚠", "·"
except (UnicodeEncodeError, LookupError):
    _PASS, _FAIL, _WARN, _SKIP = "+", "X", "!", "."

_steps_passed = 0
_steps_failed = 0
_steps_warned = 0
_issues: list[str] = []
_fixes: list[str] = []


def _ok(msg: str):
    global _steps_passed
    _steps_passed += 1
    print(f"    {_PASS} {msg}")


def _fail(msg: str, fix: str = ""):
    global _steps_failed
    _steps_failed += 1
    print(f"    {_FAIL} {msg}")
    _issues.append(msg)
    if fix:
        _fixes.append(fix)


def _warn(msg: str):
    global _steps_warned
    _steps_warned += 1
    print(f"    {_WARN} {msg}")


def _skip(msg: str):
    print(f"    {_SKIP} {msg}")


def _section(title: str):
    print(f"\n  {title}")
    print(f"  {'-' * len(title)}")


def _run(cmd: list[str], desc: str, fatal: bool = False) -> bool:
    """Run a subprocess, return success. Show first few error lines on failure."""
    print(f"    Running: {desc}...")
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            # Force UTF-8 with lossy replacement so non-ASCII pip/yt-dlp output
            # never crashes on Windows (cp1252) or constrained Linux locales.
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            first_lines = "\n      ".join(stderr.splitlines()[:5]) if stderr else "no output"
            if fatal:
                _fail(desc, fix=f"Run manually: {' '.join(cmd)}")
            else:
                _warn(f"{desc} -- {first_lines}")
            return False
        _ok(desc)
        return True
    except FileNotFoundError:
        _fail(f"{desc} -- command not found: {cmd[0]}", fix=f"Install {cmd[0]} and retry")
        return False
    except subprocess.TimeoutExpired:
        _fail(f"{desc} -- timed out (5 min)", fix=f"Check network and retry: {' '.join(cmd)}")
        return False
    except Exception as e:
        _fail(f"{desc} -- {e}")
        return False


def _prompt(msg: str, default: str = "") -> str:
    """Prompt with optional default. Handles EOFError for non-interactive."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"    {msg}{suffix}: ").strip()
        return value or default
    except (EOFError, KeyboardInterrupt):
        print()
        return default


def _confirm(msg: str, default_yes: bool = True) -> bool:
    hint = "Y/n" if default_yes else "y/N"
    try:
        answer = input(f"    {msg} [{hint}] ").strip().lower()
        if not answer:
            return default_yes
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return default_yes


def _is_in_venv() -> bool:
    """Check if running inside a virtual environment."""
    return (
        hasattr(sys, "real_prefix")  # virtualenv
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)  # venv
        or os.environ.get("CONDA_DEFAULT_ENV") is not None  # conda
        or os.environ.get("VIRTUAL_ENV") is not None  # generic
    )


def _secure_file(path: Path):
    """Set file permissions to owner-only on Unix (secrets file)."""
    if platform.system() != "Windows":
        with contextlib.suppress(OSError):
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600


# ── Check functions ──────────────────────────────────────────────


def check_platform():
    """Show platform info for diagnostics."""
    _section("Platform")
    system = platform.system()
    release = platform.release()
    arch = platform.machine()
    _ok(f"{system} {release} ({arch})")

    # Python location helps debug PATH issues
    _ok(f"Python: {sys.executable}")

    # Virtual environment check
    if _is_in_venv():
        venv = os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_DEFAULT_ENV") or "active"
        _ok(f"Virtual environment: {venv}")
    else:
        if system == "Darwin":
            _warn(
                "Not in a virtual environment -- "
                "Homebrew Python may need: python3 -m venv .venv && source .venv/bin/activate"
            )
        elif system == "Linux":
            _warn(
                "Not in a virtual environment -- "
                "recommended: python3 -m venv .venv && source .venv/bin/activate"
            )
        else:
            _warn(
                "Not in a virtual environment -- "
                "recommended: python -m venv .venv && .venv\\Scripts\\activate"
            )


def check_python():
    _section("Python")
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 10):
        _fail(
            f"Python {version_str} -- need 3.10+",
            fix="Install Python 3.10+ from https://python.org",
        )
        return False
    _ok(f"Python {version_str}")

    # Check pip
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode == 0:
            # Extract pip version from output like "pip 24.0 from /path..."
            pip_version = result.stdout.strip().split()[1] if result.stdout else "unknown"
            _ok(f"pip {pip_version}")
        else:
            _fail("pip not working", fix="Run: python -m ensurepip --upgrade")
            return False
    except Exception:
        _fail("pip not found", fix="Run: python -m ensurepip --upgrade")
        return False

    return True


def check_package(install: bool = True) -> bool:
    _section("Distill Package")

    # Check if pyproject.toml exists (are we in the right directory?)
    if not (ROOT / "pyproject.toml").exists():
        _fail(
            "pyproject.toml not found -- are you in the distill directory?",
            fix=f"cd to the distill project root (expected: {ROOT})",
        )
        return False

    # Check if already installed
    installed = False
    try:
        dist = importlib.metadata.version("distillr")
        _ok(f"distillr {dist} installed")
        installed = True
    except importlib.metadata.PackageNotFoundError:
        if install:
            if not _run(
                [sys.executable, "-m", "pip", "install", "-e", "."],
                "pip install -e .",
                fatal=True,
            ):
                return False
            installed = True
        else:
            _fail("distill not installed", fix="Run: pip install -e .")
            return False

    if not installed:
        return False

    # Verify we can actually import it
    try:
        import distill  # noqa: F401

        _ok("import distill works")
    except Exception as e:
        _fail(f"import distill failed: {e}", fix="Run: pip install -e .")
        return False

    # Verify the CLI entrypoint exists
    if shutil.which("distill"):
        _ok("distill command on PATH")
    else:
        _warn("distill not on PATH -- restart your shell after install")

    return True


def check_browser(install: bool = True) -> bool:
    _section("Browser (YouTube search)")

    # Check if playwright is importable
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _warn("playwright not importable -- will be installed with the package")
        return False

    # Check if Chromium is installed and launchable
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        _ok("Chromium browser ready")
        return True
    except Exception:
        pass  # Not installed yet, fall through to install

    if not install:
        _warn("Chromium not installed (needed for distill search/explore)")
        return False

    # On Linux, use --with-deps to install system libraries automatically
    cmd = [sys.executable, "-m", "playwright", "install"]
    if platform.system() == "Linux":
        cmd.append("--with-deps")
    cmd.append("chromium")

    if _run(cmd, "Installing Chromium"):
        return True

    # If --with-deps failed on Linux, suggest manual install
    if platform.system() == "Linux":
        _warn(
            "If Chromium install failed, you may need: sudo apt install libgbm1 libnss3 libatk-bridge2.0-0"
        )

    return False


def check_env_file() -> tuple[str, str]:
    """Check .env exists and has keys. Returns (xai_key, gemini_key)."""
    _section("API Keys (.env)")

    xai_key = ""
    gemini_key = ""

    if ENV_FILE.exists():
        _ok(".env found")

        # Parse .env -- try dotenv first, fall back to manual parse
        try:
            from dotenv import dotenv_values

            vals = dotenv_values(ENV_FILE)
        except ImportError:
            vals = {}
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    vals[k.strip()] = v.strip()

        xai_key = vals.get("XAI_API_KEY", "")
        gemini_key = vals.get("GEMINI_API_KEY", "")

        if xai_key:
            masked = f"{'*' * 8}{xai_key[-4:]}" if len(xai_key) > 4 else "****"
            _ok(f"XAI_API_KEY: {masked}")
        else:
            _fail("XAI_API_KEY not set", fix="Add your key to .env")

        if gemini_key:
            masked = f"{'*' * 8}{gemini_key[-4:]}" if len(gemini_key) > 4 else "****"
            _ok(f"GEMINI_API_KEY: {masked}")
        else:
            _warn("GEMINI_API_KEY not set (needed for reports, not required for analysis)")

        # Check file permissions on Unix
        if platform.system() != "Windows":
            mode = ENV_FILE.stat().st_mode
            if mode & stat.S_IROTH or mode & stat.S_IRGRP:
                _warn(".env is readable by other users -- fixing permissions")
                _secure_file(ENV_FILE)

    else:
        _warn(".env not found")

    return xai_key, gemini_key


def create_env() -> tuple[str, str]:
    """Interactively create .env file. Returns (xai_key, gemini_key)."""
    _section("Create .env")

    print()
    print("    Distill needs two API keys:")
    print("      1. XAI (Grok)  -- powers all video analysis")
    print("      2. Gemini      -- powers report generation (optional)")
    print()

    xai_key = _prompt("XAI_API_KEY (get one at https://console.x.ai)")
    if xai_key and not xai_key.startswith("xai-"):
        _warn("XAI keys usually start with 'xai-' -- double-check your key")

    gemini_key = _prompt("GEMINI_API_KEY (get one at https://aistudio.google.com/apikey)")

    scribe_path = ""
    if _confirm("Do you have scribe for local transcription?", default_yes=False):
        scribe_path = _prompt("SCRIBE_PATH (full path to scribe binary)")
        if scribe_path and not Path(scribe_path).exists():
            _warn(f"Path does not exist: {scribe_path}")

    # Build .env from template or scratch
    if ENV_EXAMPLE.exists():
        content = ENV_EXAMPLE.read_text(encoding="utf-8")
    else:
        content = (
            "# Distill API Keys\n"
            "# Get XAI key at: https://console.x.ai/\n"
            "XAI_API_KEY=\n\n"
            "# Get Gemini key at: https://aistudio.google.com/apikey\n"
            "GEMINI_API_KEY=\n\n"
            "# Optional: Path to scribe for audio-only transcription fallback\n"
            "# SCRIBE_PATH=\n"
        )

    if xai_key:
        content = content.replace("XAI_API_KEY=", f"XAI_API_KEY={xai_key}", 1)
    if gemini_key:
        content = content.replace("GEMINI_API_KEY=", f"GEMINI_API_KEY={gemini_key}", 1)
    if scribe_path:
        content = content.replace("# SCRIBE_PATH=", f"SCRIBE_PATH={scribe_path}")

    ENV_FILE.write_text(content, encoding="utf-8")
    _secure_file(ENV_FILE)
    _ok("Saved .env")

    if not xai_key:
        _fail("XAI_API_KEY not provided", fix="Edit .env and add your XAI key")

    return xai_key, gemini_key


def update_env_keys(xai_key: str, gemini_key: str) -> tuple[str, str]:
    """Update specific keys in existing .env."""
    print()
    new_xai = _prompt("New XAI_API_KEY (Enter to keep current)")
    new_gemini = _prompt("New GEMINI_API_KEY (Enter to keep current)")

    if not new_xai and not new_gemini:
        _skip("No changes")
        return xai_key, gemini_key

    content = ENV_FILE.read_text(encoding="utf-8")
    if new_xai:
        xai_key = new_xai
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("XAI_API_KEY="):
                lines[i] = f"XAI_API_KEY={new_xai}"
                break
        content = "\n".join(lines) + "\n"

    if new_gemini:
        gemini_key = new_gemini
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("GEMINI_API_KEY="):
                lines[i] = f"GEMINI_API_KEY={new_gemini}"
                break
        content = "\n".join(lines) + "\n"

    ENV_FILE.write_text(content, encoding="utf-8")
    _ok("Updated .env")

    return xai_key, gemini_key


def validate_api_keys(xai_key: str, gemini_key: str):  # noqa: C901 — legacy, will refactor
    """Test API keys with minimal live calls."""
    _section("Validate API Keys (live test)")

    if xai_key:
        print("    Testing XAI (Grok)...")
        try:
            import openai

            client = openai.OpenAI(
                api_key=xai_key,
                base_url="https://api.x.ai/v1",
                timeout=15.0,
            )
            resp = client.chat.completions.create(
                model="grok-3-mini-fast",
                messages=[{"role": "user", "content": "say ok"}],
                max_tokens=3,
            )
            if resp.choices:
                _ok("XAI API key works")
            else:
                _fail("XAI returned empty response", fix="Check your key at https://console.x.ai/")
        except ImportError:
            _warn("openai package not installed -- cannot test XAI key")
        except Exception as e:
            err = str(e)
            if "401" in err or "auth" in err.lower():
                _fail("XAI key rejected (401)", fix="Check your key at https://console.x.ai/")
            elif "429" in err or "rate" in err.lower():
                _warn("XAI rate-limited -- key is valid but busy, try again later")
            elif "timeout" in err.lower() or "connect" in err.lower():
                _warn(f"XAI connection failed -- check internet ({err[:80]})")
            else:
                _fail(f"XAI API error: {err[:100]}", fix="Verify key at https://console.x.ai/")
    else:
        _skip("XAI key not set -- skipping")

    if gemini_key:
        print("    Testing Gemini...")
        try:
            from google import genai

            client = genai.Client(api_key=gemini_key)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents="say ok",
            )
            if resp.text:
                _ok("Gemini API key works")
            else:
                _fail("Gemini returned empty response")
        except ImportError:
            _warn("google-genai package not installed -- cannot test Gemini key")
        except Exception as e:
            err = str(e)
            if "401" in err or "403" in err or "API_KEY_INVALID" in err:
                _fail(
                    "Gemini key rejected",
                    fix="Check your key at https://aistudio.google.com/apikey",
                )
            elif "429" in err or "quota" in err.lower():
                _warn("Gemini quota exceeded -- key is valid but rate-limited")
            elif "timeout" in err.lower() or "connect" in err.lower():
                _warn(f"Gemini connection failed -- check internet ({err[:80]})")
            else:
                _fail(f"Gemini API error: {err[:100]}")
    else:
        _skip("Gemini key not set -- skipping (needed for reports only)")


def check_yt_dlp():
    """Verify yt-dlp works."""
    _section("yt-dlp (YouTube access)")
    try:
        import yt_dlp

        _ok(f"yt-dlp {yt_dlp.version.__version__}")
    except ImportError:
        _fail("yt-dlp not importable", fix="Run: pip install yt-dlp")
        return

    # Quick sanity check -- can it reach YouTube?
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(
                "https://www.youtube.com/watch?v=jNQXAC9IVRw",
                download=False,
            )
            if info and info.get("title"):
                _ok(f"YouTube reachable (fetched: {info['title'][:40]})")
            else:
                _warn("yt-dlp ran but returned no data")
    except Exception as e:
        _warn(f"YouTube unreachable: {str(e)[:80]}")


def check_library():
    """Check library directory structure."""
    _section("Library")
    lib_dir = ROOT / "library"
    if lib_dir.exists():
        lib_file = lib_dir / "library.json"
        if lib_file.exists():
            import json

            try:
                data = json.loads(lib_file.read_text(encoding="utf-8"))
                topics = list(data.get("topics", {}).keys())
                watchlist = data.get("watchlist", [])
                _ok(f"library.json -- {len(topics)} topic(s), {len(watchlist)} watched")
            except Exception:
                _warn("library.json exists but couldn't parse")
        else:
            _ok("Library directory exists (no data yet)")
    else:
        _skip("No library yet (created on first run)")


def setup_completion():  # noqa: C901 — legacy, will refactor
    """Offer to install shell tab-completion."""
    _section("Shell Completion")

    shell = None
    shell_name = ""
    system = platform.system()

    if system == "Windows":
        if shutil.which("pwsh") or shutil.which("powershell"):
            shell = "powershell"
            shell_name = "PowerShell"
        else:
            _skip("cmd.exe -- no tab-completion (use PowerShell for best experience)")
            return
    elif system == "Darwin":
        # macOS defaults to zsh since Catalina
        user_shell = os.environ.get("SHELL", "")
        if "zsh" in user_shell:
            shell = "zsh"
            shell_name = "Zsh"
        elif "bash" in user_shell:
            shell = "bash"
            shell_name = "Bash"
        elif "fish" in user_shell:
            shell = "fish"
            shell_name = "Fish"
        else:
            shell = "zsh"
            shell_name = "Zsh (default macOS shell)"
    else:
        # Linux
        user_shell = os.environ.get("SHELL", "")
        if "zsh" in user_shell:
            shell = "zsh"
            shell_name = "Zsh"
        elif "bash" in user_shell:
            shell = "bash"
            shell_name = "Bash"
        elif "fish" in user_shell:
            shell = "fish"
            shell_name = "Fish"
        else:
            _skip(f"Unknown shell ({user_shell}) -- run 'distill --install-completion' manually")
            return

    if _confirm(f"Install tab-completion for {shell_name}?"):
        if _run(
            ["distill", "--install-completion", shell],
            f"{shell_name} completion",
        ):
            print("      Restart your shell to activate")
    else:
        _skip(f"Run 'distill --install-completion {shell}' later")


def show_summary():
    """Print final summary with issues and next steps."""
    print()
    print(f"  {'=' * 48}")

    if _steps_failed == 0:
        print(f"  {_PASS} All checks passed ({_steps_passed} passed", end="")
        if _steps_warned:
            print(f", {_steps_warned} warnings", end="")
        print(")")
    else:
        print(f"  {_FAIL} {_steps_failed} issue(s) to fix:\n")
        for issue in _issues:
            print(f"    {_FAIL} {issue}")
        if _fixes:
            print("\n  How to fix:")
            for fix in _fixes:
                print(f"    {fix}")
        print("\n  Then run: python scripts/setup.py --check")

    print(f"""
  Quick start:
    distill                              Dashboard
    distill latest "your topic"          Learn something fast
    distill watch add <channel-url>      Watch a channel
    distill catch-up                     Refresh watched channels

  Verify anytime:
    python scripts/setup.py --check              Re-run all checks
    distill doctor                       API + system health
  {"=" * 48}
""")


# ── Main ─────────────────────────────────────────────────────────


def main():
    check_only = "--check" in sys.argv

    print()
    title = "Distill -- Health Check" if check_only else "Distill -- Setup"
    width = 44
    padding = (width - len(title)) // 2
    print(f"  {'=' * width}")
    print(f"  {' ' * padding}{title}")
    print(f"  {'=' * width}")

    # 0. Platform info
    check_platform()

    # 1. Python + pip
    if not check_python():
        sys.exit(1)

    # 2. Package
    if not check_package(install=not check_only) and not check_only:
        sys.exit(1)

    # 3. yt-dlp
    check_yt_dlp()

    # 4. Browser
    check_browser(install=not check_only)

    # 5. .env + API keys
    xai_key, gemini_key = check_env_file()

    if not check_only:
        if not ENV_FILE.exists():
            xai_key, gemini_key = create_env()
        elif not xai_key:
            if _confirm("XAI_API_KEY is missing. Add it now?"):
                xai_key, gemini_key = update_env_keys(xai_key, gemini_key)
        elif _confirm("Update API keys?", default_yes=False):
            xai_key, gemini_key = update_env_keys(xai_key, gemini_key)

    # 6. Validate keys
    validate_api_keys(xai_key, gemini_key)

    # 7. Library
    check_library()

    # 8. Shell completion (setup only)
    if not check_only:
        setup_completion()

    # Summary
    show_summary()

    sys.exit(1 if _steps_failed > 0 else 0)


if __name__ == "__main__":
    main()
