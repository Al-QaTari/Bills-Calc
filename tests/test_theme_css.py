"""Tests for light/dark theme CSS loading."""

import os
from unittest.mock import MagicMock, patch

import utils

CSS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "css")


def _injected():
    with patch.object(utils.st, "markdown", MagicMock()) as md, patch.object(
        utils.st, "html", MagicMock()
    ) as html:
        utils.load_light_theme_css(CSS_DIR)
        return (
            [c.args[0] for c in md.call_args_list],
            [(c.args[0], c.kwargs) for c in html.call_args_list],
        )


def test_light_css_is_scoped_to_real_light_theme():
    styles, scripts = _injected()
    assert len(styles) == 1
    css = styles[0].replace("<style>", "").replace("</style>", "")
    assert 'html[data-app-theme="light"]' in css
    assert "--text-primary: #0f172a" in css
    # كل قاعدة لازم تبدأ بالـ scope (مفيش قاعدة فاتحة تتسرب على الوضع الغامق)
    import re

    for sel in re.findall(r"([^{}]+)\{", css):
        for part in sel.split(","):
            assert part.strip().startswith('html[data-app-theme="light"]'), part


def test_theme_sync_script_runs_with_javascript_enabled():
    _, scripts = _injected()
    assert len(scripts) == 1
    body, kwargs = scripts[0]
    assert kwargs.get("unsafe_allow_javascript") is True
    assert "data-app-theme" in body and "backgroundColor" in body


def test_scope_function_handles_root_and_lists():
    out = utils.scope_css_to_light_theme(
        ":root { --a: 1; } /* c */ .x, .y > b { color: red; }"
    )
    assert 'html[data-app-theme="light"] { --a: 1; }' in out
    assert (
        'html[data-app-theme="light"] .x, html[data-app-theme="light"] .y > b' in out
    )


def test_light_rules_count_matches_source():
    with open(os.path.join(CSS_DIR, "light.css"), encoding="utf-8") as f:
        src = f.read()
    assert utils.scope_css_to_light_theme(src).count("{") == src.count("{")


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
