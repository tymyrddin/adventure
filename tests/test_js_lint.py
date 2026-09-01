"""A tiny, dependency-free lint for the hand-written JavaScript."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "editor" / "static" / "graph.js"
AUTHORED = [FRONTEND, *sorted((ROOT / "tools" / "harness").glob("*.mjs"))]


def _code(path):
    """Return the file with comments and string bodies blanked, leaving only code."""
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", src)
    src = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', src)
    src = re.sub(r"`(?:\\.|[^`\\])*`", "``", src, flags=re.S)
    return src


def _hits(pattern, code):
    """Return the 1-based line numbers where the pattern appears in code."""
    return [n for n, line in enumerate(code.splitlines(), 1) if re.search(pattern, line)]


def test_strict():
    assert FRONTEND.read_text(encoding="utf-8").lstrip().startswith('"use strict";')


def test_no_var():
    for path in AUTHORED:
        assert _hits(r"\bvar\b", _code(path)) == [], path.name


def test_no_eqeq():
    """=== and !== only: == and != coerce their operands and hide bugs."""
    for path in AUTHORED:
        code = _code(path)
        assert _hits(r"(?<![=!<>])==(?!=)", code) == [], path.name
        assert _hits(r"!=(?!=)", code) == [], path.name


def test_no_debugger():
    """A debugger statement is a breakpoint left in the tree."""
    for path in AUTHORED:
        assert _hits(r"\bdebugger\b", _code(path)) == [], path.name


def test_no_console():
    assert _hits(r"\bconsole\.", _code(FRONTEND)) == []
