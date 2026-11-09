"""Diagnostic normalization must never rewrite bytes relayed to the user."""

import json
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("case", json.loads((Path(__file__).parents[1] / "fixtures/conpty_python313.json").read_text(encoding="utf-8")))
def test_original_vt_bytes_forwarded_before_full_explanation(case):
    raw = case["text"].encode("utf-8")
    result = subprocess.run([sys.executable, "-m", "errlens", "run", "--lang", case["language"], "--",
                             sys.executable, "-c", f"import os,sys;os.write(2,{raw!r});sys.exit(1)"],
                            capture_output=True, timeout=20)
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr.startswith(raw)
    addition = result.stderr[len(raw):].decode("utf-8")
    assert ("Имя не определено" if case["language"] == "ru" else "Undefined name") in addition
