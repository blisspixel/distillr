"""Tests for distill.banner."""

from rich.console import Console

from distill.banner import (
    BANNER_ART,
    _animate_sweep,
    _detect_capabilities,
    _ease_in_out_cubic,
    _is_banner_enabled,
    _precise_sleep,
    _precompute_gradient,
    _render_ansi_frame,
    colorize_banner,
    render_banner_plain,
    render_banner_static,
    show_banner,
)


class TestIsBannerEnabled:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("DISTILL_BANNER", raising=False)
        assert _is_banner_enabled() is True

    def test_disabled_with_off(self, monkeypatch):
        monkeypatch.setenv("DISTILL_BANNER", "off")
        assert _is_banner_enabled() is False

    def test_disabled_with_false(self, monkeypatch):
        monkeypatch.setenv("DISTILL_BANNER", "false")
        assert _is_banner_enabled() is False

    def test_disabled_with_zero(self, monkeypatch):
        monkeypatch.setenv("DISTILL_BANNER", "0")
        assert _is_banner_enabled() is False

    def test_disabled_with_no(self, monkeypatch):
        monkeypatch.setenv("DISTILL_BANNER", "no")
        assert _is_banner_enabled() is False

    def test_enabled_with_on(self, monkeypatch):
        monkeypatch.setenv("DISTILL_BANNER", "on")
        assert _is_banner_enabled() is True

    def test_enabled_with_empty(self, monkeypatch):
        monkeypatch.setenv("DISTILL_BANNER", "")
        assert _is_banner_enabled() is True


class TestDetectCapabilities:
    def test_returns_tuple_of_bools(self):
        result = _detect_capabilities()
        assert isinstance(result, tuple)
        assert len(result) == 4
        assert all(isinstance(v, bool) for v in result)


class TestEaseInOutCubic:
    def test_zero(self):
        assert _ease_in_out_cubic(0.0) == 0.0

    def test_half(self):
        assert _ease_in_out_cubic(0.5) == 0.5

    def test_one(self):
        assert _ease_in_out_cubic(1.0) == 1.0

    def test_monotonic(self):
        """Values should increase monotonically from 0 to 1."""
        prev = 0.0
        for i in range(1, 11):
            t = i / 10.0
            val = _ease_in_out_cubic(t)
            assert val >= prev
            prev = val


class TestPrecomputeGradient:
    def test_returns_list_of_correct_length(self):
        codes = _precompute_gradient(50)
        assert len(codes) == 50

    def test_single_width(self):
        codes = _precompute_gradient(1)
        assert len(codes) == 1

    def test_codes_are_ansi_strings(self):
        codes = _precompute_gradient(10)
        for code in codes:
            assert code.startswith("\033[")


class TestRenderBannerPlain:
    def test_returns_ascii_text(self):
        result = render_banner_plain(BANNER_ART)
        assert result == BANNER_ART
        assert "DISTILL" not in result  # raw art uses box-drawing chars


class TestRenderBannerStatic:
    def test_returns_rich_markup(self):
        result = render_banner_static(BANNER_ART)
        assert "[bold rgb(" in result
        assert len(result) > len(BANNER_ART)


class TestColorizeBanner:
    def test_full_sweep(self):
        art = "AB\nCD"
        result = colorize_banner(art, sweep_progress=1.0)
        assert "[bold rgb(" in result
        assert "A" in result

    def test_no_sweep(self):
        art = "AB\nCD"
        result = colorize_banner(art, sweep_progress=0.0)
        # All characters should be muted (dim)
        assert "[dim]" in result

    def test_empty_art(self):
        assert colorize_banner("") == ""

    def test_spaces_only(self):
        result = colorize_banner("   ")
        assert "   " in result


class TestRenderAnsiFrame:
    def test_basic_frame(self):
        lines = ["AB", "CD"]
        gradient = _precompute_gradient(2)
        muted = "\033[38;2;96;96;96m"
        result = _render_ansi_frame(lines, 2, 1.0, gradient, muted)
        assert "A" in result
        assert "B" in result
        assert "\n" in result

    def test_spaces_preserved(self):
        lines = ["A B"]
        gradient = _precompute_gradient(3)
        muted = "\033[38;2;96;96;96m"
        result = _render_ansi_frame(lines, 3, 1.0, gradient, muted)
        assert " " in result

    def test_partial_sweep(self):
        lines = ["ABCD"]
        gradient = _precompute_gradient(4)
        muted = "\033[38;2;96;96;96m"
        result = _render_ansi_frame(lines, 4, 0.5, gradient, muted)
        # Should contain both gradient and muted codes
        assert muted in result


class TestPreciseSleep:
    def test_returns_immediately_for_past_time(self):
        import time

        # Target in the past should return immediately
        _precise_sleep(time.perf_counter() - 1.0)

    def test_sleeps_briefly_for_near_future(self):
        import time

        start = time.perf_counter()
        _precise_sleep(start + 0.001)  # 1ms in the future
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1  # should complete quickly

    def test_sleeps_for_longer_target(self):
        import time

        start = time.perf_counter()
        _precise_sleep(start + 0.01)  # 10ms in the future
        elapsed = time.perf_counter() - start
        assert elapsed >= 0.005  # should actually wait


class TestShowBanner:
    def test_returns_false_when_disabled(self, monkeypatch):
        monkeypatch.setenv("DISTILL_BANNER", "off")
        console = Console(record=True, width=120, force_terminal=True)
        result = show_banner(console)
        assert result is False

    def test_returns_false_when_not_tty(self, monkeypatch):
        monkeypatch.delenv("DISTILL_BANNER", raising=False)
        monkeypatch.delenv("CI", raising=False)
        # Use a non-TTY console (file=StringIO)
        import io

        console = Console(file=io.StringIO(), width=120)
        result = show_banner(console)
        assert result is False

    def test_renders_plain_when_no_color(self, monkeypatch):
        import io

        import distill.banner as banner_mod

        monkeypatch.delenv("DISTILL_BANNER", raising=False)
        monkeypatch.setattr(banner_mod, "_detect_capabilities", lambda: (True, False, False, False))
        buf = io.StringIO()
        console = Console(file=buf, width=120, force_terminal=True, color_system=None)
        result = show_banner(console, art="TEST ART")
        assert result is True

    def test_renders_static_when_dumb_terminal(self, monkeypatch):
        import io

        import distill.banner as banner_mod

        monkeypatch.delenv("DISTILL_BANNER", raising=False)
        monkeypatch.setattr(banner_mod, "_detect_capabilities", lambda: (True, False, True, False))
        buf = io.StringIO()
        console = Console(file=buf, width=120, force_terminal=True, color_system="truecolor")
        result = show_banner(console, art="TEST")
        assert result is True

    def test_uses_animation_when_advanced_terminal(self, monkeypatch):
        import distill.banner as banner_mod

        called = []
        monkeypatch.delenv("DISTILL_BANNER", raising=False)
        monkeypatch.setattr(banner_mod, "_detect_capabilities", lambda: (True, False, False, False))
        monkeypatch.setattr(banner_mod, "_animate_sweep", lambda console, art, duration=1.5: called.append(art))
        console = Console(record=True, width=120, force_terminal=True, color_system="truecolor")

        result = show_banner(console, art="TEST")

        assert result is True
        assert called == ["TEST"]

    def test_returns_false_in_ci(self, monkeypatch):
        import distill.banner as banner_mod

        monkeypatch.delenv("DISTILL_BANNER", raising=False)
        monkeypatch.setattr(banner_mod, "_detect_capabilities", lambda: (True, True, False, False))
        console = Console(record=True, width=120, force_terminal=True)
        result = show_banner(console)
        assert result is False


class TestAnimateSweep:
    def test_writes_frames_and_restores_cursor(self, monkeypatch):
        import io

        monkeypatch.setattr("distill.banner._precise_sleep", lambda _target: None)
        monkeypatch.setattr("distill.banner.time.perf_counter", lambda: 0.0)
        console = Console(file=io.StringIO(), width=120, force_terminal=True, color_system="truecolor")

        _animate_sweep(console, art="AB\nCD", duration=0.02)

        output = console.file.getvalue()
        assert "\033[?25l" in output
        assert "\033[?25h" in output

    def test_falls_back_to_static_banner_on_error(self, monkeypatch):
        import io

        console = Console(file=io.StringIO(), width=120, force_terminal=True, color_system="truecolor")
        monkeypatch.setattr(
            "distill.banner._precompute_gradient",
            lambda _width: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        _animate_sweep(console, art="AB", duration=0.02)

        output = console.file.getvalue()
        assert "\033[?25h" in output
        assert "A" in output
        assert "B" in output
