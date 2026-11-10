"""Child arguments must not become ErrLens options after COMMAND."""

from importlib.metadata import version

import pytest
from typer.testing import CliRunner

import errlens
from errlens.cli import app

runner = CliRunner()


def test_all_modules_import() -> None:
    from importlib import import_module
    from pkgutil import walk_packages

    for module in walk_packages(errlens.__path__, prefix="errlens."):
        import_module(module.name)


def test_import_and_version() -> None:
    assert errlens.__version__ == version("errlens-cli") == "0.1.0"
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"ErrLens {errlens.__version__}"


@pytest.mark.parametrize("arguments", [["--help"], ["run", "--help"]])
def test_help(arguments: list[str]) -> None:
    result = runner.invoke(app, arguments)
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


@pytest.mark.parametrize("arguments", [
    ["python", "--help"], ["python", "--version"],
    ["python", "-c", "raise SystemExit(99)"],
    ["python", "script.py", "--unknown=value", "-x"],
    ["--", "python", "--help"],
])
def test_run_routes_arguments(arguments: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    from errlens import cli
    from errlens.models import ExecutionResult

    monkeypatch.setattr(cli, "run_command", lambda *args: ExecutionResult(7))
    result = runner.invoke(app, ["run", *arguments])
    assert result.exit_code == 7
    assert result.stderr == ""
    assert result.stdout == ""


def test_child_arguments_preserve_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from functools import wraps
    from errlens import cli
    from errlens.models import ExecutionResult

    monkeypatch.setattr(cli, "run_command", lambda *args: ExecutionResult(7))

    received: list[str] = []
    original = cli.run

    @wraps(original)
    def record(command: list[str], lang: str = "ru", no_explain: bool = False, terminal_mode: str = "pipe") -> None:
        received.extend(command)
        original(command, lang, no_explain, terminal_mode)

    monkeypatch.setattr(app.registered_commands[0], "callback", record)
    arguments = ["python", "a b.py", "--help", "--version", "-x", "", "Привет"]
    result = runner.invoke(app, ["run", *arguments])
    assert result.exit_code == 7
    assert received == arguments


def test_run_requires_command() -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 2
    assert "Missing argument" in result.stderr
