"""A tiny, dependency-free lint for the hand-written JavaScript.

The editor's front end has no npm toolchain by design (see tools/harness/README), so
its mechanical floor lives here, in the Python suite that already runs. It reads the
authored JS as text and enforces a handful of high-signal rules. It is not a parser:
comments and the bodies of strings are blanked first, so their contents are never
mistaken for code, and it does not touch the vendored, minified cytoscape.min.js. One
known limit follows from being a text check rather than a parser: a rule cannot see
into a template literal's ${...} expressions, since the whole literal is blanked.
"""

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


def test_frontend_declares_strict_mode():
    """graph.js is a classic script, so it must ask for strict mode itself."""
    assert FRONTEND.read_text(encoding="utf-8").lstrip().startswith('"use strict";')


def test_no_var_declarations():
    """const and let only: var's function scope is a footgun worth banning outright."""
    for path in AUTHORED:
        assert _hits(r"\bvar\b", _code(path)) == [], path.name


def test_no_loose_equality():
    """=== and !== only: == and != coerce their operands and hide bugs."""
    for path in AUTHORED:
        code = _code(path)
        assert _hits(r"(?<![=!<>])==(?!=)", code) == [], path.name
        assert _hits(r"!=(?!=)", code) == [], path.name


def test_no_debugger_statements():
    """A debugger statement is a breakpoint left in the tree."""
    for path in AUTHORED:
        assert _hits(r"\bdebugger\b", _code(path)) == [], path.name


def test_no_console_in_shipped_frontend():
    """Leftover console output has no place in the front end that ships; the dev
    harness, which is a command-line reporter, may use it freely."""
    assert _hits(r"\bconsole\.", _code(FRONTEND)) == []
