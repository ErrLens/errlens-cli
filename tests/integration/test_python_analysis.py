"""Real interpreter output passes through Runner/Capture unchanged before analysis."""

from dataclasses import asdict
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from errlens.capture import Capture
from errlens.models import ExecutionContext
from errlens.runner import run
from errlens.service import analyze_capture

CASES = [
    ("ModuleNotFoundError", "import errlens_missing_module_8f14e"),
    ("ImportError", "from math import errlens_missing_name_8f14e"),
    ("SyntaxError", "compile('if True print(1)', 'invalid source.py', 'exec')"),
    ("IndentationError", "compile('if True:\\nprint(1)', 'indent.py', 'exec')"),
    ("TabError", "compile('if True:\\n\\tpass\\n        pass', 'tabs.py', 'exec')"),
    ("NameError", "print(errlens_missing_name_8f14e)"),
    ("TypeError", "1 + 'x'"),
    ("AttributeError", "'x'.missing_attribute_8f14e"),
    ("KeyError", "{}['missing']"),
    ("FileNotFoundError", "open('errlens_missing_file_8f14e')"),
    ("PermissionError", "raise PermissionError(13, 'Permission denied', 'private.txt')"),
    ("CustomProblem", "class CustomProblem(Exception): pass\nraise CustomProblem('custom')"),
    ("ExceptionGroup", "raise ExceptionGroup('group', [ValueError('bad'), TypeError('bad')])"),
]


@pytest.mark.parametrize("error_type,code", CASES, ids=[case[0] for case in CASES])
def test_real_errors_via_runner(error_type: str, code: str, tmp_path: Path) -> None:
    context = ExecutionContext([sys.executable, "-c", code], str(tmp_path))
    capture, stdout, stderr = Capture(), io.BytesIO(), io.BytesIO()
    result = run(context, capture, stdout, stderr)
    assert result.exit_code == 1
    assert stdout.getvalue() == b"" and stderr.getvalue() == capture.stderr.data
    before = stdout.getvalue(), stderr.getvalue(), asdict(result)
    diagnostics = analyze_capture(context, result, capture)
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.error_type == error_type
    assert not diagnostic.incomplete and diagnostic.frames
    assert diagnostic.complex_structure == (error_type == "ExceptionGroup")
    assert before == (stdout.getvalue(), stderr.getvalue(), asdict(result))


def test_real_chained_exception_and_multiline(tmp_path: Path) -> None:
    code = "try:\n    1/0\nexcept ZeroDivisionError as exc:\n    raise RuntimeError('first\\nsecond') from exc"
    capture = Capture()
    context = ExecutionContext([sys.executable, "-c", code], str(tmp_path))
    result = run(context, capture, io.BytesIO(), io.BytesIO())
    found = analyze_capture(context, result, capture)
    assert [item.error_type for item in found] == ["ZeroDivisionError", "RuntimeError"]
    assert found[1].chain_relation == "cause"
    assert found[1].related_diagnostic_id == found[0].diagnostic_id
    assert found[1].original_message == "first\nsecond"


def test_stdout_traceback_from_real_interpreter(tmp_path: Path) -> None:
    code = "import traceback,sys\ntry:\n    1/0\nexcept Exception:\n    traceback.print_exc(file=sys.stdout)\n    sys.exit(1)"
    context = ExecutionContext([sys.executable, "-c", code], str(tmp_path))
    capture, stdout, stderr = Capture(), io.BytesIO(), io.BytesIO()
    result = run(context, capture, stdout, stderr)
    found = analyze_capture(context, result, capture)
    assert len(found) == 1 and found[0].source == "stdout"
    assert stderr.getvalue() == b"" and stdout.getvalue() == capture.stdout.data


def test_cli_traceback_still_matches_direct_execution(tmp_path: Path) -> None:
    child = [sys.executable, "-c", "raise TypeError('unchanged')"]
    direct = subprocess.run(child, cwd=tmp_path, capture_output=True, timeout=15)
    wrapped = subprocess.run([sys.executable, "-m", "errlens", "run", "--no-explain", "--", *child],
                             cwd=tmp_path, capture_output=True, timeout=15)
    assert (wrapped.stdout, wrapped.stderr, wrapped.returncode) == (
        direct.stdout, direct.stderr, direct.returncode)


def test_recorded_cpython_corpus() -> None:
    from errlens.analyzers.python import PythonAnalyzer
    from errlens.capture import CapturedData
    from errlens.models import ExecutionResult

    path = Path(__file__).parents[1] / "fixtures" / "recorded_python313.json"
    corpus = json.loads(path.read_text(encoding="utf-8"))
    for case in corpus["cases"]:
        found = PythonAnalyzer().analyze(
            ExecutionContext(["python3.13"], "."), ExecutionResult(1),
            CapturedData(stderr=case["stderr"]),
        )
        assert [item.error_type for item in found] == [case["error_type"]]
        assert not found[0].incomplete
