# pyright: strict
"""WCAG contrast and bounded Oklab lightness adjustment for theme data."""

from __future__ import annotations

import math
import re


def color(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is None:
        raise ValueError("colors must be strict #rrggbb values")
    return value.lower()


def _rgb(value: str) -> tuple[float, float, float]:
    return int(value[1:3], 16) / 255, int(value[3:5], 16) / 255, int(value[5:7], 16) / 255


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _encode(channel: float) -> float:
    return 12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055


def _hex(channels: tuple[float, ...]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in channels)


def luminance(value: str) -> float:
    r, g, b = (_linear(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def mix(first: str, second: str, fraction: float) -> str:
    return _hex(
        tuple(
            a * (1 - fraction) + b * fraction
            for a, b in zip(_rgb(first), _rgb(second), strict=True)
        )
    )


def oklab(value: str) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in _rgb(value))
    cone_l = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * cone_l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * cone_l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * cone_l + 0.7827717662 * m - 0.8086757660 * s,
    )


def _from_oklab(lightness: float, a: float, b: float) -> str | None:
    cone_l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    channels = (
        4.0767416621 * cone_l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * cone_l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * cone_l - 0.7034186147 * m + 1.7076147010 * s,
    )
    if any(c < -0.000001 or c > 1.000001 for c in channels):
        return None
    return _hex(tuple(_encode(max(0, c)) for c in channels))


def repair_contrast(value: str, backgrounds: tuple[str, ...], minimum: float) -> str:
    if all(contrast(value, bg) >= minimum for bg in backgrounds):
        return value
    lightness, a, b = oklab(value)
    candidates = sorted(range(1001), key=lambda step: abs(step / 1000 - lightness))
    for step in candidates:
        candidate = _from_oklab(step / 1000, a, b)
        if candidate is not None and all(contrast(candidate, bg) >= minimum for bg in backgrounds):
            return candidate
    raise ValueError("contrast cannot be repaired while preserving hue and chroma")


def distinct_statuses(success: str, error: str) -> bool:
    light_s, a_s, b_s = oklab(success)
    light_e, a_e, b_e = oklab(error)
    hue_delta = abs(math.degrees(math.atan2(b_s, a_s) - math.atan2(b_e, a_e))) % 360
    return min(hue_delta, 360 - hue_delta) >= 60 or abs(light_s - light_e) >= 0.15
