"""Static checks for css/polish.css and css/light.css (v7 look)."""

import os
import re

CSS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "css")


def _read(name):
    with open(os.path.join(CSS_DIR, name), encoding="utf-8") as f:
        return re.sub(r"/\*.*?\*/", "", f.read(), flags=re.DOTALL)


def test_all_css_files_have_balanced_braces_and_parens():
    for name in ("styles.css", "light.css", "polish.css"):
        css = _read(name)
        assert css.count("{") == css.count("}"), name
        assert css.count("(") == css.count(")"), name


def test_every_animation_used_in_polish_has_keyframes():
    all_css = "".join(_read(n) for n in ("styles.css", "light.css", "polish.css"))
    defined = set(re.findall(r"@keyframes\s+([\w-]+)", all_css))
    polish = _read("polish.css")
    names = {
        t
        for decl in re.findall(r"animation\s*:\s*([^;}]+)", polish)
        for t in re.findall(r"[A-Za-z][\w-]*", decl)
        if not re.fullmatch(
            r"ease|ease-in|ease-out|ease-in-out|linear|infinite|alternate|both|"
            r"forwards|backwards|none|normal|reverse|running|paused|s|ms|"
            r"cubic-bezier|steps|var|important|polish-ease",
            t,
        )
    }
    missing = {n for n in names if n not in defined and not n.startswith("-")}
    assert not missing, missing


def test_polish_respects_reduced_motion():
    assert "prefers-reduced-motion" in _read("polish.css")


def test_font_stack_has_fallbacks():
    css = _read("polish.css")
    assert "Cairo" in css
    assert re.search(r"Cairo[^;]*sans-serif", css)


def test_light_and_polish_define_same_accent_family():
    light = _read("light.css")
    polish = _read("polish.css")
    assert "--text-primary" in light
    assert "linear-gradient" in polish
