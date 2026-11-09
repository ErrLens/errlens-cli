"""End-to-end byte preservation plus localized reports, with bounded execution."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from errlens.cli import app


def execute(code: str, *, options=(), arguments=(), cwd=None):
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["FORCE_COLOR"] = "1"  # redirected reports must still be plain
    return subprocess.run([sys.executable, "-m", "errlens", "run", *options, "--",
                           sys.executable, "-c", code, *arguments], capture_output=True,
                          cwd=cwd, env=environment, timeout=15)


@pytest.mark.parametrize("code,fragment", [
    ("import requests_nonexistent_example", "Модуль недоступен"),
    ("print(undefined_variable)", "Имя не определено"),
    ("open('missing_file_example.txt')", "Файл или компонент пути не найден"),
])
def test_real_requested_examples(code: str, fragment: str, tmp_path: Path) -> None:
    result = execute(code, cwd=tmp_path)
    plain = execute(code, options=("--no-explain",), cwd=tmp_path)
    assert result.returncode == plain.returncode == 1
    assert result.stdout == plain.stdout == b""
    assert result.stderr.startswith(plain.stderr)
    addition = result.stderr[len(plain.stderr):].decode("utf-8")
    assert fragment in addition and "ErrLens" in addition
    assert "\x1b" not in addition and "pip install" not in addition


@pytest.mark.parametrize("lang,phrase", [("ru", "Имя не определено"), ("en", "Undefined name")])
def test_languages(lang: str, phrase: str) -> None:
    result = execute("print(undefined_variable)", options=("--lang", lang))
    assert phrase in result.stderr.decode("utf-8")
    assert result.returncode == 1


@pytest.mark.parametrize("code", ["print('ok')", "import sys; sys.exit(7)",
    "import traceback\ntry:\n    1/0\nexcept Exception:\n    traceback.print_exc()"])
def test_no_report_for_success_or_unstructured_failure(code: str) -> None:
    result = execute(code)
    assert b"ErrLens" not in result.stdout + result.stderr


def test_stdout_bytes_and_failure_exit_code_preserved() -> None:
    result = execute("import os,sys; os.write(1,bytes(range(256))); "
                     "raise NameError('observed')")
    assert result.stdout == bytes(range(256)) and result.returncode == 1
    assert "Имя не определено" in result.stderr.decode("utf-8")


def test_child_options_are_not_errlens_options() -> None:
    result = execute("import sys; print(repr(sys.argv[1:]))",
                     arguments=("--lang", "en", "--no-explain", "a b", "Привет"))
    assert result.returncode == 0
    assert result.stdout.decode("utf-8").strip() == repr(["--lang", "en", "--no-explain", "a b", "Привет"])


def test_unknown_is_neutral_and_chain_has_one_report() -> None:
    code = "try:\n    {}['root']\nexcept KeyError as exc:\n    raise RuntimeError('final') from exc"
    result = execute(code, options=("--lang", "en"))
    text = result.stderr.decode("utf-8")
    assert text.count("ErrLens · Error detected") == 1
    assert "No verified explanation" in text and "Earlier linked exceptions" in text
    assert "Possible causes:" not in text and "KeyError: 'root'" in text


def test_group_has_one_outer_report() -> None:
    result = execute("raise ExceptionGroup('many', [NameError('x'), TypeError('y')])",
                     options=("--lang", "en"))
    text = result.stderr.decode("utf-8")
    assert text.count("ErrLens · Error detected") == 1
    assert "only the outer level" in " ".join(text.split())


def test_internal_analysis_failure_preserves_output_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from errlens import cli
    def broken(*args, **kwargs):
        raise RuntimeError("private detail")
    monkeypatch.setattr(cli, "explain_capture", broken)
    result = CliRunner().invoke(app, ["run", sys.executable, "-c",
                                     "import os,sys; os.write(1,b'raw'); os.write(2,b'error'); sys.exit(7)"])
    assert result.exit_code == 7 and result.stdout == "raw"
    assert result.stderr.startswith("error") and "ErrLens" in result.stderr
    assert "private detail" not in result.stderr


def test_no_explain_skips_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    from errlens import cli
    def forbidden(*args, **kwargs):
        raise AssertionError("analysis must not be called")
    monkeypatch.setattr(cli, "explain_capture", forbidden)
    result = CliRunner().invoke(app, ["run", "--no-explain", "--", sys.executable,
                                     "-c", "raise NameError('original')"])
    assert result.exit_code == 1 and "ErrLens" not in result.stderr


def test_renderer_failure_preserves_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    from errlens import cli
    def broken(*args, **kwargs):
        raise ValueError("render failed")
    monkeypatch.setattr(cli, "render_report", broken)
    result = CliRunner().invoke(app, ["run", sys.executable, "-c", "raise NameError('original')"])
    assert result.exit_code == 1 and "NameError: original" in result.stderr
    assert "ValueError" in result.stderr and "Не удалось подготовить объяснение" in result.stderr
    assert "Обнаружена ошибка" not in result.stderr


def test_ansi_in_traceback_is_preserved_but_not_replayed_in_report() -> None:
    code = "raise NameError('[bold red]literal[/bold red] \\x1b[2J')"
    raw = execute(code, options=("--no-explain",))
    result = execute(code)
    assert result.returncode == raw.returncode == 1
    assert result.stderr.startswith(raw.stderr) and b"\x1b[2J" in raw.stderr
    addition = result.stderr[len(raw.stderr):].decode("utf-8")
    assert "\x1b" not in addition and "[bold red]literal[/bold red]" in addition


def test_incomplete_capture_has_notice_and_no_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    from errlens import cli
    from errlens.models import ExecutionResult
    def fake(context, capture, stdout, stderr):
        data = (b'Traceback (most recent call last):\n  File "main.py", line 1\n'
                b"ModuleNotFoundError: No module named 'requests'\n")
        stderr.write(data)
        capture.append("stderr", data)
        return ExecutionResult(1, output_complete=False)
    monkeypatch.setattr(cli, "run_command", fake)
    result = CliRunner().invoke(app, ["run", sys.executable, "main.py"])
    assert result.exit_code == 1 and "Диагностика неполная" in result.stderr
    assert "pip" not in result.stderr and "Возможные причины:" not in result.stderr


def test_suggested_install_is_displayed_without_spawning_any_process(monkeypatch: pytest.MonkeyPatch) -> None:
    from errlens import cli
    from errlens.models import ExecutionResult
    def fake(context, capture, stdout, stderr):
        data = (b'Traceback (most recent call last):\n  File "main.py", line 1\n'
                b"ModuleNotFoundError: No module named 'requests'\n")
        stderr.write(data)
        capture.append("stderr", data)
        return ExecutionResult(1)
    def forbidden(*args, **kwargs):
        raise AssertionError("No extra processes may be launched")
    monkeypatch.setattr(cli, "run_command", fake)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = CliRunner().invoke(app, ["run", "--lang", "en", "--", sys.executable, "main.py"])
    assert result.exit_code == 1
    assert "pip" in result.stderr and "install" in result.stderr and "requests" in result.stderr
    assert "Only if requests" in result.stderr and "Could not prepare" not in result.stderr


def test_bad_language_is_usage_error() -> None:
    result = execute("raise AssertionError('must not run')", options=("--lang", "de"))
    assert result.returncode == 2 and b"must not run" not in result.stderr
