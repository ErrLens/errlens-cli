"""Opt-in profile changes and real shell scenarios, always using temporary profiles."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from errlens.powershell import manage, quote


def test_profile_roundtrip(tmp_path: Path) -> None:
    profile = tmp_path / "профиль с пробелами.ps1"
    original = b"# user settings\r\n$custom = 1"  # no final newline
    profile.write_bytes(original)
    manage("install", profile)
    installed = profile.read_bytes()
    assert installed.startswith(original)
    manage("install", profile)
    assert profile.read_bytes() == installed
    assert len(list(tmp_path.glob("*.errlens-backup-*"))) == 1
    assert "installed:" in manage("status", profile)
    manage("uninstall", profile)
    assert profile.read_bytes() == original
    manage("uninstall", profile)
    assert profile.read_bytes() == original


def test_new_profile_and_foreign_file(tmp_path: Path) -> None:
    profile = tmp_path / "profile.ps1"
    manage("install", profile)
    integration = tmp_path / "ErrLens" / "profile.ps1.python.ps1"
    integration.write_text("# user content", encoding="utf-8")
    with pytest.raises(ValueError, match="unowned"):
        manage("uninstall", profile)
    assert integration.read_text() == "# user content"


PWSH = shutil.which("pwsh")


def invoke(tmp_path: Path, body: str, *, path: str | None = None):
    profile = tmp_path / "profile.ps1"
    manage("install", profile)
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    if path is not None:
        environment["PATH"] = path
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command",
        ". " + quote(str(profile)) + "; " + body], cwd=tmp_path, env=environment,
        capture_output=True, timeout=25)


@pytest.mark.skipif(not PWSH, reason="PowerShell 7 is unavailable")
@pytest.mark.parametrize("code,status,explain", [("print('Hello')", 0, False),
    ("print(undefined_variable)", 1, True), ("import sys;sys.exit(7)", 7, False)])
def test_real_python(tmp_path: Path, code: str, status: int, explain: bool) -> None:
    result = invoke(tmp_path, "python -c " + quote(code) + "; exit $LASTEXITCODE",
                    path=str(Path(sys.executable).parent))
    assert result.returncode == status, result.stderr
    assert ("ErrLens ·".encode() in result.stderr) == explain


@pytest.mark.skipif(not PWSH, reason="PowerShell 7 is unavailable")
def test_arguments_cwd_and_missing_errlens_path(tmp_path: Path) -> None:
    code = "import sys,os,json;print(json.dumps([sys.argv[1:],os.getcwd()],ensure_ascii=False))"
    args = ["a b", 'a"b', "Привет", "", "--version"]
    body = "python -c " + quote(code) + " " + " ".join(map(quote,args)) + "; exit $LASTEXITCODE"
    result = invoke(tmp_path, body, path=str(Path(sys.executable).parent))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [args, str(tmp_path)]


@pytest.mark.skipif(not PWSH, reason="PowerShell 7 is unavailable")
def test_disable_absolute_pipeline_and_redirect(tmp_path: Path) -> None:
    body = "$env:ERRLENS_DISABLE='1'; python -c 'print(undefined_variable)'; "
    body += "$code=$LASTEXITCODE; "
    body += "python -c 'print(123)' | Set-Content result.txt; "
    body += "python -c 'print(456)' > redirected.txt; "
    body += "& " + quote(sys.executable) + " --version; exit $code"
    result = invoke(tmp_path, body)
    assert result.returncode == 1 and "ErrLens ·".encode() not in result.stderr
    assert (tmp_path / "result.txt").read_text(encoding="utf-8-sig").strip() == "123"
    assert (tmp_path / "redirected.txt").read_text(encoding="utf-8-sig").strip() == "456"


@pytest.mark.skipif(not PWSH, reason="PowerShell 7 is unavailable")
def test_virtual_environment_and_conflict(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=30)
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    result = invoke(tmp_path, "python -c 'import sys;print(sys.prefix)'; exit $LASTEXITCODE", path=str(scripts))
    assert result.returncode == 0 and str(venv) in result.stdout.decode()
    profile = tmp_path / "profile.ps1"
    result = subprocess.run([PWSH, "-NoProfile", "-Command",
        "function python { 'user function' }; . " + quote(str(profile)) + "; python"], capture_output=True, timeout=15)
    assert b"user function" in result.stdout


@pytest.mark.skipif(not PWSH, reason="PowerShell 7 is unavailable")
def test_version_status_and_unwrapped_commands(tmp_path: Path) -> None:
    body = "python --version; python -c 'import sys;sys.exit(7)'; $ok=$?; $code=$LASTEXITCODE; "
    body += "[Console]::WriteLine(('STATUS={0};OK={1}' -f $code,$ok)); "
    body += "& " + quote(sys.executable) + " --version; "
    body += "if (Get-Command py -ErrorAction SilentlyContinue) { (Get-Command py).CommandType }; exit 0"
    result = invoke(tmp_path, body)
    assert result.returncode == 0 and b"STATUS=7;OK=True" in result.stdout
    assert result.stdout.count(b"Python ") == 2
    assert b"ErrLens" not in result.stderr
