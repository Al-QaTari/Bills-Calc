"""One RTL rule for the whole app, and the help/admin markdown fixes."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _rtl_block():
    css = _read("css/styles.css")
    assert "12. اتجاه موحّد" in css
    return css.split("12. اتجاه موحّد", 1)[1]


def test_global_rtl_rule_covers_markdown_and_widgets():
    block = _rtl_block()
    for selector in (
        '[data-testid="stMarkdownContainer"]',
        '[data-testid="stElementContainer"]',
        '[data-testid="stCaptionContainer"]',
        '[data-testid="stAlert"]',
        '[data-testid="stExpanderDetails"]',
        '[data-testid="stWidgetLabel"]',
    ):
        assert selector in block, selector
    assert "direction: rtl" in block
    assert "text-align: start" in block


def test_lists_have_logical_padding_so_bullets_stay_next_to_text():
    block = _rtl_block()
    assert "padding-inline-start" in block
    assert "list-style-position: outside" in block


def test_code_stays_ltr():
    block = _rtl_block()
    assert re.search(r"pre,[^{]*code\s*\{[^}]*direction:\s*ltr", block, re.S)


def test_admin_blocks_follow_rtl():
    block = _rtl_block()
    for cls in (".admin-header", ".admin-metric", ".admin-alert"):
        assert cls in block


def test_ledger_css_no_longer_centers_page_wide_text():
    src = _read("ui/portfolio.py")
    css = src.split('_CENTER_CSS = """', 1)[1].split('"""', 1)[0]
    for selector in (
        "stCaptionContainer",
        "stAlert",
        "stWidgetLabel",
        "stRadio",
        'stForm"],[data-testid="stCheckbox"]',
    ):
        assert selector not in css, selector


def test_help_page_has_no_literal_markdown_stars():
    src = _read("ui/help_page.py")
    assert "**" not in src
    assert "dedent(" in src
    assert "<b>كيف تعمل؟</b>" in src


def test_help_page_text_is_dedented_at_runtime(monkeypatch):
    import streamlit as st

    from ui import help_page

    bodies = []

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(st, "expander", lambda *a, **k: _Ctx())
    monkeypatch.setattr(st, "markdown", lambda body, *a, **k: bodies.append(body))
    help_page.render_help_page()
    assert len(bodies) >= 5
    for body in bodies:
        indents = [
            len(line) - len(line.lstrip()) for line in body.splitlines() if line.strip()
        ]
        # dedent leaves the least-indented line at column 0, so no top-level
        # line can turn into a markdown code block
        assert min(indents) == 0
        assert "**" not in body
    joined = "\n".join(bodies)
    assert "<b>مثال عملي:</b>" in joined


def test_admin_telegram_guide_is_not_an_indented_code_block():
    src = _read("secret_admin_panel.py")
    assert "`.env`" in src
    assert 'st.markdown("""\n                    1.' not in src.replace("\r\n", "\n")
