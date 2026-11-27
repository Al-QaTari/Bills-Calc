"""Dependabot config: monthly, both ecosystems kept, major bumps ignored.

No yaml module on purpose: CI installs only requirements.txt, which has no
YAML parser. The file is simple enough to parse by lines.
"""

import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / ".github" / "dependabot.yml"


def _blocks():
    text = CONFIG.read_text(encoding="utf-8")
    lines = [ln.rstrip() for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(lines)
    assert re.search(r"^version:\s*2\s*$", body, re.M)
    parts = re.split(r"^\s*-\s+package-ecosystem:", body, flags=re.M)[1:]
    assert parts, "no update blocks found"
    return {p.split("\n", 1)[0].strip().strip('"'): p for p in parts}


def test_both_ecosystems_present():
    assert set(_blocks()) == {"pip", "github-actions"}


def test_each_block_is_monthly_at_root():
    for name, block in _blocks().items():
        assert re.search(r'directory:\s*"/"', block), name
        assert re.search(r'interval:\s*"monthly"', block), name


def test_major_updates_ignored_everywhere():
    for name, block in _blocks().items():
        assert re.search(r'dependency-name:\s*"\*"', block), name
        assert "version-update:semver-major" in block, name
        assert "minor" not in block.split("ignore:")[1], name
        assert "patch" not in block.split("ignore:")[1], name


def test_file_uses_lf_and_is_utf8():
    raw = CONFIG.read_bytes()
    raw.decode("utf-8")
    assert b"\r" not in raw
