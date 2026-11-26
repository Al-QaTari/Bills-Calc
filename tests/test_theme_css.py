"""Tests for light/dark theme CSS loading."""

import os
from unittest.mock import MagicMock, patch

import utils

CSS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "css")


def _injected_css(theme_type):
    with patch.object(
        utils, "get_streamlit_theme_type", return_value=theme_type
    ), patch.object(utils.st, "markdown", MagicMock()) as md:
        utils.load_light_theme_css(CSS_DIR)
        return [c.args[0] for c in md.call_args_list]


def test_light_theme_injects_light_css():
    calls = _injected_css("light")
    assert len(calls) == 1
    assert "--text-primary: #0f172a" in calls[0]
    assert "@media" not in calls[0].split("--text-primary")[0]


def test_dark_theme_injects_nothing():
    assert _injected_css("dark") == []


def test_unknown_theme_wraps_in_media_query():
    calls = _injected_css(None)
    assert len(calls) == 1
    assert "@media (prefers-color-scheme: light)" in calls[0]


def test_theme_detection_failure_returns_none():
    ctx = MagicMock()
    type(ctx).theme = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("no ctx"))
    )
    with patch.object(utils.st, "context", ctx):
        assert utils.get_streamlit_theme_type() is None


def test_light_css_has_balanced_braces():
    with open(os.path.join(CSS_DIR, "light.css"), encoding="utf-8") as f:
        css = f.read()
    assert css.count("{") == css.count("}")


def test_polish_css_injected_with_emoji_font_and_reduced_motion():
    with patch.object(utils.st, "markdown", MagicMock()) as md:
        utils.load_polish_css(CSS_DIR)
    css = md.call_args.args[0]
    assert "unicode-range" in css
    assert "prefers-reduced-motion" in css
    assert "border-radius" in css


def test_polish_css_missing_file_is_safe(tmp_path):
    with patch.object(utils.st, "markdown", MagicMock()) as md:
        utils.load_polish_css(str(tmp_path))
    md.assert_not_called()


def test_v7_typography_and_pulse_rules_present():
    from pathlib import Path

    css = Path("css/polish.css").read_text(encoding="utf-8")
    light = Path("css/light.css").read_text(encoding="utf-8")
    assert "Cairo" in css and "@keyframes heartbeat" in css
    assert "prefers-reduced-motion" in css
    assert "--btn-fg" in light and "--hero-bg" in light
