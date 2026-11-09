"""Line-local diagnostic normalization, including captured Actions #5 data."""

import json
from pathlib import Path

import pytest

from errlens.analyzers.python import _COLUMN_LIMIT, _COPY_LIMIT, _diagnostic_text, PythonAnalyzer
from errlens.capture import CapturedData, TerminalCapture
from errlens.i18n import Translator
from errlens.models import ExecutionContext, ExecutionResult
from errlens.render import render_report
from errlens.service import explain_capture


@pytest.mark.parametrize("raw,expected", [
    ("\x1b[10C^^^^^^^^\r\n", "          ^^^^^^^^\n"),
    ("abc\x1b[2Cz\n", "abc  z\n"),
    ("abcdefghij\r\x1b[2C^\n", "ab^defghij\n"),
    ("abc\x1b[2D^\n", "a^c\n"),
    ("abc\x1b[2G^\n", "a^c\n"),
    ("abc\r\x1b[2X\x1b[2C^\n", "  ^\n"),
    ("abc\r\x1b[K\x1b[2C^\n", "  ^\n"),
    ("abc\x1b[2K\x1b[C^\n", "    ^\n"),
    ("abc\n\x1b[C^\n", "abc\n ^\n"),
    ("abc\r\n\x1b[0C^\n", "abc\n ^\n"),
    ("\x1b[31m界e\u0301\x1b[0m\x1b[2CЯ\n", "界e\u0301  Я\n"),
    ("a\t\x1b[C^\n", "a        ^\n"),
    ("abc\b\x1b[C^\n", "abc^\n"),
])
def test_cursor_position_is_preserved(raw, expected):
    assert _diagnostic_text(raw) == (expected, False)


@pytest.mark.parametrize("parameter", ["4095", "4096", "4097", "999999999999999999999999999999", "9" * 10000])
def test_cursor_expansion_is_bounded(parameter):
    result, limited = _diagnostic_text("\x1b[" + parameter + "C^\n")
    assert len(result) <= _COLUMN_LIMIT + 1
    if int(parameter[:5]) > _COLUMN_LIMIT:
        assert limited


def test_total_expansion_is_bounded_and_incomplete():
    raw = "\x1b[4095C^\n" * 1000
    text, limited = _diagnostic_text(raw)
    assert limited and len(text) <= _COPY_LIMIT
    traceback = 'Traceback (most recent call last):\n  File "main.py", line 1\n'
    found = PythonAnalyzer().analyze(ExecutionContext(["python"], "."), ExecutionResult(1),
        CapturedData(combined=traceback + "\x1b[999999999999999999C^\nNameError: x\n"))
    assert len(found) == 1 and found[0].incomplete


def test_plain_text_and_zero_parameters():
    raw = "Привет 🌍\r\nmultiple\nlines\n"
    assert _diagnostic_text(raw) == (raw, False)
    assert _diagnostic_text("\x1b[" + "0" * 10000 + "C^\n") == (" ^\n", False)
    text, limited = _diagnostic_text("a" + "\u0301" * 10000 + "\x1b[C^\n")
    assert limited and len(text) < 100
    text, limited = _diagnostic_text("\u0301" * 100000 + "\x1b[C^\n")
    assert limited and text == " ^\n"
    text, limited = _diagnostic_text("x" * (_COPY_LIMIT + 1))
    assert limited and len(text) == _COPY_LIMIT


@pytest.mark.parametrize("case", json.loads((Path(__file__).parents[1] / "fixtures/conpty_python313.json").read_text(encoding="utf-8")))
def test_recorded_ci_tracebacks_produce_full_card_without_mutating_capture(case):
    capture = TerminalCapture()
    original = case["text"].encode("utf-8")
    capture.combined.append(original)
    context = ExecutionContext(["python", "-c", "print(undefined_variable)"], ".")
    report = explain_capture(context, ExecutionResult(1), capture)
    assert report is not None and not report.diagnostic.incomplete
    assert report.explanation.rule_id == "python.name_error"
    language = case["language"]
    rendered = render_report(report, Translator(language), terminal=False)
    assert ("Имя не определено" if language == "ru" else "Undefined name") in rendered
    assert capture.combined.data == original


def test_plain_unicode_colors_crlf_and_multiline_message():
    raw = 'Traceback (most recent call last):\r\n  File "путь.py", line 1\r\n    f()\r\n\x1b[4C^\r\nValueError: Привет\r\nsecond line\r\n\x1b[0m'
    found = PythonAnalyzer().analyze(ExecutionContext(["python"], "."), ExecutionResult(1), CapturedData(stderr=raw))
    assert len(found) == 1 and not found[0].incomplete
    assert found[0].file_path == "путь.py"
    assert found[0].original_message == "Привет\nsecond line"
