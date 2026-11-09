"""Literal user text, terminal wrapping and plain output without ANSI."""

from dataclasses import asdict
import shlex
import sys

import pytest
from rich.text import Text

from errlens.i18n import Translator
from errlens.models import Diagnostic, ExecutionContext, ExplanationReport
from errlens.render import format_command, render_report, safe_text
from errlens.rules.python import explain


def report(message="name 'x' is not defined", *, incomplete=False):
    diagnostic = Diagnostic("id", "NameError", message,
        file_path="C:\\мой проект\\" + "long directory\\" * 10 + "main.py", line_number=3,
        parameters={"name": "[bold red]x[/bold red]"}, incomplete=incomplete)
    return ExplanationReport(diagnostic, explain(diagnostic, ExecutionContext([sys.executable], ".")))


@pytest.mark.parametrize("locale", ["ru", "en"])
def test_plain_output_and_literal_markup(locale: str) -> None:
    value = report("[link=https://evil]literal[/link]\x1b[2J\r\u202e")
    before = asdict(value)
    output = render_report(value, Translator(locale), terminal=False)
    assert "ErrLens" in output and "\x1b" not in output and "\u202e" not in output
    assert "[bold red]x[/bold red]" in output
    assert "\\x1b" in output and "\\u202e" in output
    assert "╭" not in output
    assert asdict(value) == before


@pytest.mark.parametrize("width", [20, 30, 40, 80])
def test_terminal_wraps_without_losing_text(width: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    output = render_report(report(), Translator(), terminal=True, width=width)
    plain = Text.from_ansi(output).plain
    assert all(Text(line).cell_len <= width for line in plain.splitlines())
    assert "\x1b[" in output
    assert "ErrLens" in plain


def test_no_color_even_on_terminal() -> None:
    output = render_report(report(), Translator(), terminal=True, color=False)
    assert "\x1b" not in output


def test_incomplete_notice() -> None:
    output = render_report(report(incomplete=True), Translator("en"), terminal=False)
    assert "Incomplete diagnostic" in output and "Possible causes:" not in output


def test_shell_quoting() -> None:
    argv = ["/my path/python", "-m", "pip", "install", "requests"]
    assert shlex.split(format_command(argv, windows=False)) == argv
    assert format_command(["C:\\a'b\\python.exe", "requests;evil"], windows=True) == "& 'C:\\a''b\\python.exe' 'requests;evil'"


def test_safe_text_bounds_controls_and_preserves_unicode() -> None:
    assert safe_text("Привет 🌍") == "Привет 🌍"
    assert safe_text("x" * 100, limit=5) == "xxxxx…"
    assert safe_text("\x00\x07\n\r") == "\\x00\\x07\\x0a\\x0d"
