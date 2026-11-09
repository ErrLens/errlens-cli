"""Run from outside the repository to avoid accidental local imports.

CI executes this suite against a clean wheel install as well as editable mode.
These subprocesses test the installed ErrLens entry points.
"""

import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest


@pytest.mark.parametrize("arguments", [["--help"], ["--version"], ["run", "--help"]])
def test_module_entry_point(arguments: list[str], tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-m", "errlens", *arguments], cwd=tmp_path,
        env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "ErrLens" in result.stdout or "Usage:" in result.stdout


def test_installed_console_script(tmp_path: Path) -> None:
    script = Path(sysconfig.get_path("scripts")) / ("errlens.exe" if os.name == "nt" else "errlens")
    result = subprocess.run([str(script), "--version"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ErrLens 0.1.0"


def test_installed_resources(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c",
         "from errlens.i18n import Translator; "
         "assert Translator('en').translate('cli.version', version='test') == 'ErrLens test'; "
         "assert Translator('ru').translate('cli.version', version='test') == 'ErrLens test'"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
