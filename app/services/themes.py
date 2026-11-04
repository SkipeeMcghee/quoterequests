"""Internal theme library.

100 palettes ship with the template as raw four-colour combinations (see
`app/data/themes.json`). This module turns each one into the semantic CSS custom
properties the stylesheet actually consumes, so a customer can switch the whole
look from a dropdown without touching CSS.

The mapping is deliberately conservative: the site is a light-UI design with some
hard-coded white surfaces, so every palette is nudged into a light background and
checked for text contrast before it is offered.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

THEMES_PATH = Path(__file__).resolve().parents[1] / "data" / "themes.json"

# The palette the stylesheet was designed around; selecting it means "emit no
# overrides at all", so the default look stays byte-identical.
DEFAULT_SLUG = "quite-clear"

MIN_TEXT_CONTRAST = 7.0
# Accent is used for link text and for button backgrounds carrying white text, so it
# has to clear normal-text contrast in both directions.
MIN_ACCENT_CONTRAST = 4.5
MIN_BACKGROUND_LUMINANCE = 0.72


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(channel))):02X}" for channel in rgb)


def _channel_luminance(channel: float) -> float:
    channel = channel / 255
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    red, green, blue = (c / 255 for c in _hex_to_rgb(color))
    return (
        0.2126 * _channel_luminance(red * 255)
        + 0.7152 * _channel_luminance(green * 255)
        + 0.0722 * _channel_luminance(blue * 255)
    )


def contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def mix(first: str, second: str, amount: float) -> str:
    """Blend `amount` of `second` into `first` (0 = first, 1 = second)."""

    a = _hex_to_rgb(first)
    b = _hex_to_rgb(second)
    return _rgb_to_hex(tuple(x + (y - x) * amount for x, y in zip(a, b)))


def _lighten_until(color: str, target_luminance: float) -> str:
    current = color
    for step in range(1, 21):
        if relative_luminance(current) >= target_luminance:
            return current
        current = mix(color, "#FFFFFF", step / 20)
    return current


def _contrast_until(color: str, background: str, target: float) -> str:
    """Push a foreground colour away from the background until it is readable."""

    if contrast_ratio(color, background) >= target:
        return color
    direction = "#000000" if relative_luminance(background) > 0.4 else "#FFFFFF"
    for step in range(1, 21):
        candidate = mix(color, direction, step / 20)
        if contrast_ratio(candidate, background) >= target:
            return candidate
    return direction


def _white_text_safe(color: str, target: float) -> str:
    """Buttons paint white text on the brand/accent colour, so it has to be dark enough."""

    if contrast_ratio("#FFFFFF", color) >= target:
        return color
    for step in range(1, 21):
        candidate = mix(color, "#000000", step / 20)
        if contrast_ratio("#FFFFFF", candidate) >= target:
            return candidate
    return "#000000"


@lru_cache(maxsize=1)
def load_themes() -> tuple[dict, ...]:
    raw = json.loads(THEMES_PATH.read_text(encoding="utf-8"))
    return tuple(raw)


def theme_slugs() -> list[str]:
    return [theme["slug"] for theme in load_themes()]


def get_theme(slug: str | None) -> dict | None:
    if not slug:
        return None
    for theme in load_themes():
        if theme["slug"] == slug:
            return theme
    return None


def build_roles(colors: list[str]) -> dict[str, str]:
    """Map four raw palette colours onto the stylesheet's semantic roles."""

    ordered = sorted(colors, key=relative_luminance)
    darkest, second_darkest = ordered[0], ordered[1]
    lightest = ordered[-1]

    background = _lighten_until(lightest, MIN_BACKGROUND_LUMINANCE)
    card = _lighten_until(mix(background, "#FFFFFF", 0.5), MIN_BACKGROUND_LUMINANCE + 0.05)
    card_solid = _lighten_until(mix(background, "#FFFFFF", 0.78), MIN_BACKGROUND_LUMINANCE + 0.1)
    neutral = _contrast_until(darkest, background, MIN_TEXT_CONTRAST)
    brand = _white_text_safe(_contrast_until(darkest, background, MIN_TEXT_CONTRAST), MIN_TEXT_CONTRAST)
    accent = _white_text_safe(
        _contrast_until(second_darkest, background, MIN_ACCENT_CONTRAST), MIN_ACCENT_CONTRAST
    )

    return {
        "background": background,
        "card": card,
        "card-solid": card_solid,
        "brand": brand,
        "accent": accent,
        "neutral": neutral,
    }


def css_variables(slug: str | None) -> dict[str, str]:
    """CSS custom properties for a slug, or {} for the built-in default theme."""

    theme = get_theme(slug)
    if theme is None or theme["slug"] == DEFAULT_SLUG:
        return {}

    roles = build_roles(theme["colors"])
    variables: dict[str, str] = {}
    for name in ("background", "brand", "accent", "neutral"):
        variables[f"--theme-{name}"] = roles[name]
        variables[f"--theme-{name}-rgb"] = ", ".join(str(c) for c in _hex_to_rgb(roles[name]))
    variables["--card"] = roles["card"]
    variables["--card-solid"] = roles["card-solid"]
    return variables


def display_name(slug: str | None) -> str:
    theme = get_theme(slug)
    return theme["name"] if theme else "Default"


# ---------------------------------------------------------------------------
# Active theme selection
#
# The choice lives in instance/theme.json so a customer can change it at runtime
# (from the admin appearance screen) without a redeploy. SITE_THEME in the
# environment is the deploy-time default for a fresh install.
# ---------------------------------------------------------------------------


def _state_path(app) -> Path:
    return Path(app.instance_path) / "theme.json"


def get_active_slug(app) -> str:
    state = _state_path(app)
    if state.exists():
        try:
            saved = json.loads(state.read_text(encoding="utf-8-sig")).get("slug")
        except (ValueError, OSError):
            saved = None
        if get_theme(saved) is not None:
            return saved
    configured = app.config.get("SITE_THEME")
    if get_theme(configured) is not None:
        return configured
    return DEFAULT_SLUG


def set_active_slug(app, slug: str) -> None:
    if get_theme(slug) is None:
        raise ValueError(f"unknown theme: {slug}")
    state = _state_path(app)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"slug": slug}, indent=2), encoding="utf-8")
