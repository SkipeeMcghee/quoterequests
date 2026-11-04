from __future__ import annotations

import json
import re

from app.services.themes import (
    DEFAULT_SLUG,
    build_roles,
    contrast_ratio,
    css_variables,
    get_active_slug,
    get_theme,
    load_themes,
    relative_luminance,
    set_active_slug,
)


def test_library_ships_every_palette_with_four_colors():
    themes = load_themes()

    assert len(themes) == 100
    slugs = [theme["slug"] for theme in themes]
    assert len(set(slugs)) == len(slugs)

    for theme in themes:
        assert theme["name"]
        assert len(theme["colors"]) == 4
        for color in theme["colors"]:
            assert re.fullmatch(r"#[0-9A-F]{6}", color), f"{theme['slug']}: {color}"


def test_every_palette_produces_a_light_surface_and_readable_text():
    failures = []
    for theme in load_themes():
        roles = build_roles(theme["colors"])
        if relative_luminance(roles["background"]) < 0.7:
            failures.append((theme["slug"], "background too dark"))
        if contrast_ratio(roles["neutral"], roles["background"]) < 7:
            failures.append((theme["slug"], "text contrast below 7:1"))
        if contrast_ratio(roles["accent"], roles["background"]) < 4.5:
            failures.append((theme["slug"], "accent text contrast below 4.5:1"))
        if contrast_ratio("#FFFFFF", roles["accent"]) < 4.5:
            failures.append((theme["slug"], "white on accent below 4.5:1"))
        if contrast_ratio("#FFFFFF", roles["brand"]) < 4.5:
            failures.append((theme["slug"], "white on brand below 4.5:1"))

    assert failures == []


def test_default_theme_emits_no_overrides():
    assert css_variables(None) == {}
    assert css_variables(DEFAULT_SLUG) == {}


def test_css_variables_cover_the_roles_the_stylesheet_uses():
    variables = css_variables("stormy-morning")

    assert variables["--theme-background"].startswith("#")
    assert variables["--theme-brand-rgb"].count(",") == 2
    assert variables["--card"] and variables["--card-solid"]


def test_default_palette_matches_the_stylesheet_baseline():
    theme = get_theme(DEFAULT_SLUG)

    assert theme is not None
    assert {color.upper() for color in theme["colors"]} == {
        "#CBCBCB", "#F2F2F2", "#174D38", "#4D1717",
    }


def test_active_theme_round_trips_through_instance_state(app, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "instance_path", str(tmp_path))

    assert get_active_slug(app) == DEFAULT_SLUG

    set_active_slug(app, "stormy-morning")
    assert get_active_slug(app) == "stormy-morning"
    assert json.loads((tmp_path / "theme.json").read_text(encoding="utf-8"))["slug"] == "stormy-morning"

    set_active_slug(app, DEFAULT_SLUG)
    assert get_active_slug(app) == DEFAULT_SLUG


def test_unknown_theme_is_rejected(app, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "instance_path", str(tmp_path))

    try:
        set_active_slug(app, "not-a-theme")
    except ValueError:
        return
    raise AssertionError("unknown theme should not be accepted")


def test_appearance_screen_lists_the_library_and_applies_a_choice(client, app, admin_user, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "instance_path", str(tmp_path))
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=True,
    )

    page = client.get("/admin/settings/appearance")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Stormy morning" in body
    assert "Summer breeze" in body

    applied = client.post(
        "/admin/settings/appearance",
        data={"theme_slug": "stormy-morning"},
        follow_redirects=True,
    )
    assert applied.status_code == 200
    assert "Appearance updated to Stormy morning." in applied.get_data(as_text=True)

    public_page = client.get("/").get_data(as_text=True)
    assert "--theme-brand:" in public_page


def test_rejects_a_theme_that_is_not_in_the_library(client, app, admin_user, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "instance_path", str(tmp_path))
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=True,
    )

    response = client.post(
        "/admin/settings/appearance",
        data={"theme_slug": "made-up"},
        follow_redirects=True,
    )

    assert "Pick a theme from the library." in response.get_data(as_text=True)
    assert get_active_slug(app) == DEFAULT_SLUG


def test_state_file_written_with_a_bom_is_still_read(app, tmp_path, monkeypatch):
    """PowerShell's Set-Content writes UTF-8 with a BOM; that must not reset the theme."""

    monkeypatch.setattr(app, "instance_path", str(tmp_path))
    (tmp_path / "theme.json").write_text(
        "\ufeff" + '{"slug": "stormy-morning"}', encoding="utf-8"
    )

    assert get_active_slug(app) == "stormy-morning"
