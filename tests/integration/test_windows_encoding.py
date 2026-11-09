"""The CLI's own text must survive Windows' non-Unicode default code pages."""

import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows code page regression")


@pytest.mark.parametrize("arguments", [["--help"], ["run", "--help"]])
@pytest.mark.parametrize("entry", ["module", "script"])
def test_help_with_cp1252(tmp_path: Path, arguments: list[str], entry: str) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "cp1252:strict", "PYTHONUTF8": "0"}
    prefix = ([sys.executable, "-m", "errlens"] if entry == "module" else
              [str(Path(sysconfig.get_path("scripts")) / "errlens.exe")])
    result = subprocess.run([*prefix, *arguments], cwd=tmp_path, env=env,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "ErrLens" in result.stdout.decode("utf-8")
    assert b"UnicodeEncodeError" not in result.stderr


def test_explanation_with_cp1252_preserves_child_bytes(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "cp1252:strict", "PYTHONUTF8": "0"}
    child = [sys.executable, "-c", "import os; os.write(1,bytes([0xff,0x80])); print(undefined_variable)"]
    direct = subprocess.run(child, cwd=tmp_path, env=env, capture_output=True, timeout=20)
    result = subprocess.run([sys.executable, "-m", "errlens", "run", *child], cwd=tmp_path,
                            env=env, capture_output=True, timeout=20)
    assert result.returncode == direct.returncode == 1
    assert result.stdout == direct.stdout == b"\xff\x80"
    assert result.stderr.startswith(direct.stderr)
    assert "Имя не определено" in result.stderr[len(direct.stderr):].decode("utf-8")
