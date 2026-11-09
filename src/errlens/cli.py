"""CLI coordination; child output bypasses Rich and translation entirely."""

import os
from pathlib import Path
import sys
import subprocess
from typing import Annotated

import typer
from rich.console import Console

from errlens import __version__
from errlens.i18n import Translator
from errlens.i18n import SUPPORTED_LOCALES
from errlens.capture import Capture
from errlens.models import ExecutionContext
from errlens.runner import RunnerError, run as run_command
from errlens.render import render_report, safe_text
from errlens.service import explain_capture

_translator = Translator()
app = typer.Typer(
    help=_translator.translate("cli.description"),
    no_args_is_help=True,
    add_completion=False,
)
shell_app = typer.Typer(help="Manage opt-in shell integration.")
app.add_typer(shell_app, name="shell")


def main_entry() -> None:
    """Use UTF-8 for our Windows text output before Typer renders help.

    Native child streams are forwarded through the underlying binary buffers,
    so changing the text wrappers does not re-encode the child's output.
    """
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                try:
                    reconfigure(encoding="utf-8", errors="backslashreplace")
                except (OSError, ValueError):
                    # Some embedded hosts expose streams that cannot be reconfigured.
                    pass
    app()


def _shell_action(action: str, shell: str, profile: Path | None) -> None:
    from errlens.powershell import default_profile, manage
    if shell not in {"powershell", "bash", "zsh"}:
        raise typer.BadParameter("Choose powershell, bash or zsh.")
    try:
        if shell == "powershell":
            typer.echo(manage(action, profile if profile is not None else default_profile()))
        else:
            from errlens import posix_shell
            typer.echo(posix_shell.manage(action, shell, profile if profile is not None else posix_shell.default_profile(shell)))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        typer.echo(f"ErrLens: {exc}", err=True)
        raise typer.Exit(1) from exc


@shell_app.command("install")
def shell_install(shell: str, profile: Annotated[Path | None, typer.Option("--profile")] = None) -> None:
    _shell_action("install", shell, profile)


@shell_app.command("uninstall")
def shell_uninstall(shell: str, profile: Annotated[Path | None, typer.Option("--profile")] = None) -> None:
    _shell_action("uninstall", shell, profile)


@shell_app.command("status")
def shell_status(shell: str, profile: Annotated[Path | None, typer.Option("--profile")] = None) -> None:
    _shell_action("status", shell, profile)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(_translator.translate("cli.version", version=__version__))
        raise typer.Exit()


def _language(value: str) -> str:
    if value not in SUPPORTED_LOCALES:
        raise typer.BadParameter("Choose ru or en.")
    return value


def _silence_failed_streams() -> None:
    """Prevent shutdown flush from replacing a child's status after pipe failure."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            try:
                with open(os.devnull, "wb") as sink:
                    os.dup2(sink.fileno(), stream.fileno())
            except (OSError, ValueError):
                pass


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Configure ErrLens."""


@app.command(
    help=_translator.translate("cli.run_help"),
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False},
)
def run(
    command: Annotated[
        list[str],
        typer.Argument(help="Executable followed by its arguments.", metavar="COMMAND [ARGS]..."),
    ],
    lang: Annotated[str, typer.Option("--lang", callback=_language, help="Explanation language: ru or en.")] = "ru",
    no_explain: Annotated[bool, typer.Option("--no-explain", help="Forward output without explanations.")] = False,
) -> None:
    """Forward child bytes literally and propagate its termination status."""
    translator = Translator(lang)
    context = ExecutionContext(command, str(Path.cwd()))
    capture = Capture()
    try:
        result = run_command(
            context, capture,
            sys.stdout.buffer, sys.stderr.buffer,
        )
    except RunnerError as exc:
        if exc.kind == "broken_pipe":
            _silence_failed_streams()
        try:
            Console(stderr=True).print(
                translator.translate("cli.runner_error", kind=exc.kind, detail=safe_text(exc)),
                markup=False, highlight=False,
            )
        except (OSError, ValueError):
            pass  # stderr itself may be closed
        raise typer.Exit(code=exc.exit_code) from exc
    if not no_explain and result.exit_code not in (0, None) and not result.interrupted:
        try:
            report = explain_capture(context, result, capture)
            if report is not None:
                terminal = sys.stderr.isatty()
                try:
                    width = os.get_terminal_size(sys.stderr.fileno()).columns if terminal else 80
                except (OSError, ValueError):
                    width = 80
                block = render_report(report, translator, terminal=terminal, width=width,
                                      color="NO_COLOR" not in os.environ)
                sys.stderr.write(block)
                sys.stderr.flush()
        except Exception as exc:
            # Analysis/rendering is optional. Preserve the already-forwarded bytes
            # and the child's result; never turn this failure into a guessed fix.
            try:
                sys.stderr.write("\n" + translator.translate("cli.postprocess_error", kind=type(exc).__name__) + "\n")
                sys.stderr.flush()
            except (OSError, ValueError):
                _silence_failed_streams()
    code = result.exit_code if result.exit_code is not None else 125
    if result.interrupted:
        code = 130
    elif code < 0 and os.name == "posix":
        code = 128 - code
    raise typer.Exit(code=code)
