"""Render ErrLens-owned text in memory; child bytes never pass through Rich."""

import io
import os
import shlex
import unicodedata

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from errlens.i18n import Translator
from errlens.models import ExplanationReport, Parameter


def safe_text(value: object, limit: int = 2048) -> str:
    """Escape control/bidi characters, retaining literal Rich markup and Unicode."""
    raw = str(value)
    clipped = raw[:limit]
    text = "".join(
        (f"\\u{ord(character):04x}" if ord(character) > 255 else f"\\x{ord(character):02x}")
        if unicodedata.category(character).startswith("C") else character
        for character in clipped
    )
    return text + ("…" if len(raw) > limit else "")


def format_command(argv: list[str], *, windows: bool) -> str:
    """Quote display-only argv for POSIX shell or PowerShell (never cmd.exe)."""
    if windows:
        return "& " + " ".join("'" + part.replace("'", "''") + "'" for part in argv)
    return shlex.join(argv)


def render_report(
    report: ExplanationReport, translator: Translator, *, terminal: bool,
    width: int = 80, color: bool = True, windows: bool | None = None,
) -> str:
    """Stage the entire block before writing; no partial card on build failure."""
    explanation, diagnostic = report.explanation, report.diagnostic
    parameters: dict[str, Parameter] = {
        key: safe_text(value) for key, value in explanation.parameters.items()
    }

    def translated(key: str) -> str:
        return translator.translate(key, **parameters)

    body = Text(overflow="fold")
    body.append(translated(explanation.message_ids["title"]) + "\n", style="bold")
    body.append(translated(explanation.message_ids["description"]) + "\n")
    if "detail" in explanation.message_ids:
        body.append(translated(explanation.message_ids["detail"]) + "\n")
    if diagnostic.original_message:
        body.append(translator.translate("render.original", message=safe_text(diagnostic.original_message)) + "\n")
    if diagnostic.file_path is not None:
        body.append(translator.translate("render.file", path=safe_text(diagnostic.file_path)) + "\n")
    if diagnostic.line_number is not None:
        body.append(translator.translate("render.line", line=diagnostic.line_number) + "\n")
    if diagnostic.incomplete:
        body.append(translator.translate("render.incomplete") + "\n", style="bold")
    for cause in explanation.causes:
        body.append(translator.translate("render.possible") + " " + translated(cause) + "\n")
    body.append("\n" + translator.translate("render.actions") + "\n", style="bold")
    for action in explanation.actions:
        body.append("• " + translated(action) + "\n")
    for condition in explanation.conditions:
        body.append(translator.translate("render.condition") + " " + translated(condition) + "\n")
    for command in explanation.commands:
        shell = "PowerShell" if (os.name == "nt" if windows is None else windows) else "POSIX shell"
        body.append("\n" + translator.translate("render.command", shell=shell) + "\n", style="bold")
        body.append(safe_text(format_command(command.argv, windows=shell == "PowerShell"), limit=8192) + "\n")
        body.append(translated(command.condition_id) + "\n")
    if report.related:
        body.append("\n" + translator.translate("render.related") + "\n", style="bold")
        for predecessor in report.related[:5]:
            body.append("• " + safe_text(predecessor.error_type) + ": "
                        + safe_text(predecessor.original_message, limit=256) + "\n")
        if len(report.related) > 5:
            body.append(translator.translate("render.more", count=len(report.related) - 5) + "\n")
        if diagnostic.chain_relation in {"context", "cause"}:
            body.append(translator.translate("render.chain." + diagnostic.chain_relation) + "\n")
    if report.other_count:
        body.append(translator.translate("render.other", count=report.other_count) + "\n")
    output = io.StringIO()
    console = Console(file=output, force_terminal=terminal, force_jupyter=False,
                      color_system="auto" if terminal and color else None,
                      width=max(12, width), height=25, legacy_windows=False,
                      highlight=False, markup=False)
    title = Text(translator.translate("render.header"), style="bold")
    console.print()
    if terminal and width >= 30:
        console.print(Panel(body, title=title, title_align="left", border_style="blue", padding=(0, 1)))
    else:
        console.print(title)
        console.print(body)
    return output.getvalue()
