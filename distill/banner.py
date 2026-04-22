"""
Animated ASCII banner for Distill CLI.

Renders a gradient-colored wordmark with optional sweep animation,
building on the same approach as Scribe's banner system.

The animation engine bypasses Rich's rendering pipeline during playback,
writing pre-rendered ANSI escape strings directly to stdout at 60fps
with precise timing (hybrid sleep + busy-wait to defeat Windows timer
granularity). Inspired by GitHub Copilot CLI's animation approach.
"""

from __future__ import annotations

import colorsys
import os
import platform
import sys
import time

from rich.console import Console
from rich.markup import escape
from rich.text import Text

# ─── ASCII Wordmark ─────────────────────────────────────────────────────
# ANSI Shadow block font — bold 6-line design inspired by GitHub Copilot CLI.
# Uses █ (full block) for fills and ╔═╗║╚╝ (double-line box-drawing) for edges.

BANNER_ART = (
    "  ██████╗ ██╗███████╗████████╗██╗██╗     ██╗     \n"
    "  ██╔══██╗██║██╔════╝╚══██╔══╝██║██║     ██║     \n"
    "  ██║  ██║██║███████╗   ██║   ██║██║     ██║     \n"
    "  ██║  ██║██║╚════██║   ██║   ██║██║     ██║     \n"
    "  ██████╔╝██║███████║   ██║   ██║███████╗███████╗\n"
    "  ╚═════╝ ╚═╝╚══════╝   ╚═╝   ╚═╝╚══════╝╚══════╝"
)

# Brand hue range: blue (200deg) to purple (320deg)
_START_HUE = 200 / 360
_END_HUE = 320 / 360
_MUTED_COLOR = "dim"

# ANSI escape constants
_ANSI_RESET = "\033[0m"
_ANSI_HIDE_CURSOR = "\033[?25l"
_ANSI_SHOW_CURSOR = "\033[?25h"

# Animation: 60fps for buttery smooth playback
_ANIM_FPS = 60
_ANIM_FRAME_TIME = 1.0 / _ANIM_FPS


# ─── Timing ──────────────────────────────────────────────────────────────


def _ease_in_out_cubic(t: float) -> float:
    """Ease-in-out cubic for smooth animation acceleration and deceleration."""
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def _precise_sleep(target_time: float) -> None:
    """Sleep until target_time with sub-millisecond precision.

    Windows time.sleep() has ~15.6ms granularity, so a 16.7ms request
    actually sleeps ~31ms. This hybrid approach sleeps for the bulk,
    then busy-waits the final 2ms for precise frame timing.
    """
    remaining = target_time - time.perf_counter()
    if remaining <= 0:
        return
    if remaining > 0.002:
        time.sleep(remaining - 0.002)
    while time.perf_counter() < target_time:
        pass


# ─── Raw ANSI Frame Rendering ───────────────────────────────────────────


def _precompute_gradient(max_width: int) -> list[str]:
    """Pre-compute bold RGB ANSI codes for each column position."""
    codes: list[str] = []
    for col in range(max_width):
        col_ratio = col / max(1, max_width - 1)
        hue = _START_HUE + (_END_HUE - _START_HUE) * col_ratio
        r, g, b = [int(v * 255) for v in colorsys.hsv_to_rgb(hue % 1.0, 0.85, 0.92)]
        codes.append(f"\033[1;38;2;{r};{g};{b}m")
    return codes


def _render_ansi_frame(
    lines: list[str],
    max_width: int,
    sweep_progress: float,
    gradient_codes: list[str],
    muted_code: str,
) -> str:
    """Render one animation frame as a raw ANSI escape string.

    Tracks the last-emitted color code and only emits a new code
    when the color actually changes, reducing output size.
    """
    parts: list[str] = []
    for line_idx, line in enumerate(lines):
        if line_idx > 0:
            parts.append("\n")
        last_code: str | None = None
        for col, ch in enumerate(line):
            if ch == " ":
                parts.append(" ")
                last_code = None
                continue

            col_ratio = col / max(1, max_width - 1)
            code = gradient_codes[col] if col_ratio <= sweep_progress else muted_code

            if code != last_code:
                parts.append(code)
                last_code = code
            parts.append(ch)

        parts.append(_ANSI_RESET)

    return "".join(parts)


# ─── Rich Markup Rendering (static output / backward compat) ────────────


def colorize_banner(
    art: str,
    sweep_progress: float = 1.0,
    start_hue: float = _START_HUE,
    end_hue: float = _END_HUE,
    muted_color: str = _MUTED_COLOR,
) -> str:
    """
    Apply gradient coloring to ASCII art with sweep position.

    Args:
        art: Multi-line ASCII art string.
        sweep_progress: 0.0 (all muted) to 1.0 (fully colored).
        start_hue: Starting hue for gradient (0.0-1.0).
        end_hue: Ending hue for gradient (0.0-1.0).
        muted_color: Rich color string for characters not yet swept.

    Returns:
        Rich markup string with per-character gradient coloring.
    """
    lines = art.split("\n")
    if not lines:
        return ""

    max_width = max(len(line) for line in lines)
    if max_width == 0:
        return art

    result_lines: list[str] = []
    for line in lines:
        parts: list[str] = []
        for col, ch in enumerate(line):
            if ch == " ":
                parts.append(" ")
                continue

            col_ratio = col / max(1, max_width - 1)

            if col_ratio <= sweep_progress:
                hue = start_hue + (end_hue - start_hue) * col_ratio
                r, g, b = [int(v * 255) for v in colorsys.hsv_to_rgb(hue % 1.0, 0.85, 0.92)]
                parts.append(f"[bold rgb({r},{g},{b})]{escape(ch)}[/]")
            else:
                parts.append(f"[{muted_color}]{escape(ch)}[/{muted_color}]")

        result_lines.append("".join(parts))

    return "\n".join(result_lines)


def render_banner_plain(art: str) -> str:
    """Return banner as plain text with no color markup."""
    return art


def render_banner_static(art: str) -> str:
    """Return banner with full gradient applied (sweep_progress=1.0)."""
    return colorize_banner(art, sweep_progress=1.0)


def _is_banner_enabled() -> bool:
    """Check DISTILL_BANNER env var -- enabled by default."""
    val = os.environ.get("DISTILL_BANNER", "").strip().lower()
    return val not in ("off", "false", "0", "no")


def _detect_capabilities() -> tuple[bool, bool, bool, bool]:
    """Detect terminal capabilities: (is_tty, is_ci, is_dumb, is_windows)."""
    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    is_ci = os.environ.get("CI", "").strip().lower() in ("true", "1", "yes")
    is_dumb = os.environ.get("TERM", "") == "dumb"
    is_windows = platform.system() == "Windows"
    return is_tty, is_ci, is_dumb, is_windows


# ─── Banner Display ─────────────────────────────────────────────────────


def show_banner(console: Console, art: str = BANNER_ART) -> bool:
    """
    Display the banner with appropriate styling for the terminal.

    Picks animated, static, or plain rendering based on terminal
    capabilities and user preferences.

    Returns True if the banner was displayed, False if skipped.
    """
    if not _is_banner_enabled():
        return False

    is_tty, is_ci, is_dumb, _is_windows = _detect_capabilities()

    if not is_tty or is_ci:
        return False

    console.print()

    supports_advanced = is_tty and not is_dumb and not is_ci

    if not console.color_system:
        console.print(render_banner_plain(art))
    elif supports_advanced:
        _animate_sweep(console, art, duration=1.5)
    else:
        console.print(Text.from_markup(render_banner_static(art)))

    return True


def _animate_sweep(
    console: Console,
    art: str,
    duration: float = 1.5,
) -> None:
    """Animate a gradient sweep at 60fps using direct ANSI output.

    Bypasses Rich's rendering pipeline during animation for maximum
    smoothness. Pre-renders all frames as raw ANSI escape strings,
    then plays them back with precise timing and cursor repositioning.
    """
    try:
        lines = art.split("\n")
        num_lines = len(lines)
        max_width = max(len(line) for line in lines)
        total_frames = max(2, int(duration * _ANIM_FPS))

        # Pre-compute gradient ANSI codes (shared across all frames)
        gradient_codes = _precompute_gradient(max_width)
        muted_code = "\033[38;2;96;96;96m"

        # Pre-render every frame as a raw ANSI string
        frames: list[str] = []
        for f in range(total_frames + 1):
            progress = f / total_frames
            eased = _ease_in_out_cubic(progress)
            frames.append(_render_ansi_frame(lines, max_width, eased, gradient_codes, muted_code))

        out = console.file or sys.stdout
        cursor_up = f"\033[{num_lines - 1}A\r"

        # Hide cursor and render first frame
        out.write(_ANSI_HIDE_CURSOR)
        out.write(frames[0])
        out.flush()

        # Play remaining frames with precise timing
        start = time.perf_counter()
        for i in range(1, len(frames)):
            _precise_sleep(start + i * _ANIM_FRAME_TIME)
            out.write(cursor_up)
            out.write(frames[i])
            out.flush()

        # Show cursor and move to next line
        out.write(_ANSI_SHOW_CURSOR + "\n")
        out.flush()

    except Exception:
        # Ensure cursor is visible on any error
        try:
            out = console.file or sys.stdout
            out.write(_ANSI_SHOW_CURSOR + _ANSI_RESET + "\n")
            out.flush()
        except Exception:
            pass
        # Fall back to static banner via Rich
        console.print(Text.from_markup(render_banner_static(art)))
