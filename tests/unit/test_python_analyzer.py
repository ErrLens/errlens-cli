"""Corpus, detection boundaries and extracted facts, with no source-file access."""

from dataclasses import asdict
import json
from pathlib import Path
import sys

import pytest

from errlens.analyzers.base import Analyzer, AnalyzerRegistry
from errlens.analyzers.python import PythonAnalyzer
from errlens.capture import Capture, CapturedData
from errlens.models import ExecutionContext, ExecutionResult
from errlens.rules.python import RULE_IDS, rule_id_for
from errlens.service import analyze_capture

FIXTURES = Path(__file__).parents[1] / "fixtures"
CORPUS = json.loads((FIXTURES / "python_diagnostics.json").read_text(encoding="utf-8"))
HEADER = 'Traceback (most recent call last):\n  File "main.py", line 2, in <module>\n'
TRACEBACK = HEADER + "NameError: name 'x' is not defined\n"
CONTEXT = ExecutionContext([sys.executable, "main.py"], ".")


@pytest.mark.parametrize("case", CORPUS, ids=lambda case: case["name"])
def test_diagnostic_corpus(case) -> None:
    data = CapturedData(stderr=case["text"], stderr_truncated=case.get("truncated", False))
    found = PythonAnalyzer().analyze(CONTEXT, ExecutionResult(1), data)
    assert len(found) == len(case["expected"])
    for diagnostic, expected in zip(found, case["expected"]):
        actual = asdict(diagnostic)
        assert diagnostic.execution_failed is True
        assert diagnostic.source == "stderr"
        for key, value in expected.items():
            if key == "frame_count":
                assert len(diagnostic.frames) == value
            else:
                assert actual[key] == value
        json.dumps(actual)  # structured facts remain JSON-serializable


@pytest.mark.parametrize("text", [
    "", "Everything is fine", "Error count: 0", "TypeError: this is documentation",
    "ModuleNotFoundError: No module named 'x'", "Warning: be careful",
    "main.py:2: UserWarning: warning", "Traceback (most recent call last):",
    '  File "main.py", line 2, in <module>\nTypeError: bad',
    'Traceback (most recent call last):\nThis is an example\nTypeError: bad',
    '  File "main.py", line 0\nSyntaxError: bad',
    '  File "main.py", line ' + '9' * 5000 + '\nSyntaxError: bad',
    'There is a Traceback (most recent call last): in the manual',
])
@pytest.mark.parametrize("exit_code", [0, 1, None])
def test_no_false_diagnostics(text: str, exit_code: int | None) -> None:
    analyzer = PythonAnalyzer()
    assert analyzer.analyze(CONTEXT, ExecutionResult(exit_code), CapturedData(stderr=text)) == []
    assert analyzer.analyze(CONTEXT, ExecutionResult(exit_code), CapturedData(stdout=text)) == []


@pytest.mark.parametrize("code,expected", [(0, False), (1, True), (None, None)])
def test_stderr_diagnostic_is_distinct_from_execution_failure(code, expected) -> None:
    found = PythonAnalyzer().analyze(CONTEXT, ExecutionResult(code), CapturedData(stderr=TRACEBACK))
    assert len(found) == 1 and found[0].execution_failed is expected


@pytest.mark.parametrize("command,code,interrupted,count", [
    (["python", "main.py"], 1, False, 1),
    (["C:\\venv\\Scripts\\python.exe"], 1, False, 1),
    (["python3.13"], 1, False, 1), (["pypy3"], 1, False, 1),
    (["python"], 0, False, 0), (["python"], None, False, 0),
    (["python"], 1, True, 0), (["echo"], 1, False, 0),
    (["notpython"], 1, False, 0), (["python-project"], 1, False, 0),
])
def test_stdout_policy(command, code, interrupted, count) -> None:
    context = ExecutionContext(command, ".")
    found = PythonAnalyzer().analyze(context, ExecutionResult(code, interrupted),
                                     CapturedData(stdout=TRACEBACK))
    assert len(found) == count
    if found:
        assert found[0].source == "stdout"


def test_wrapped_python_and_combined_source() -> None:
    context = ExecutionContext(["custom-launcher"], ".", environment={"language": "python"})
    found = PythonAnalyzer().analyze(context, ExecutionResult(1), CapturedData(combined=TRACEBACK))
    assert len(found) == 1 and found[0].source == "combined"


def test_no_reconstruction_between_streams() -> None:
    found = PythonAnalyzer().analyze(CONTEXT, ExecutionResult(1),
                                     CapturedData(stderr=HEADER, stdout="NameError: bad"))
    assert len(found) == 1 and found[0].incomplete
    assert found[0].error_type == "UnknownPythonException"


def test_capture_service_is_pure_and_retains_truncation() -> None:
    capture = Capture(len(TRACEBACK.encode()))
    capture.append("stderr", b"discarded\n" + TRACEBACK.encode())
    context, result = CONTEXT, ExecutionResult(1, output_complete=False)
    before = capture.stderr.data, asdict(context), asdict(result)
    found = analyze_capture(context, result, capture)
    assert len(found) == 1 and found[0].incomplete
    assert before == (capture.stderr.data, asdict(context), asdict(result))
    assert capture.decoded().stderr_truncated


def test_registry_and_empty_registry_override() -> None:
    analyzer: Analyzer = PythonAnalyzer()
    registry = AnalyzerRegistry()
    registry.register(analyzer)
    capture = Capture()
    capture.append("stderr", TRACEBACK.encode())
    assert analyze_capture(CONTEXT, ExecutionResult(1), capture, registry=registry)
    assert analyze_capture(CONTEXT, ExecutionResult(1), capture, registry=AnalyzerRegistry()) == []


@pytest.mark.parametrize("message,parameters", [
    ("'x'", {"key_repr": "'x'", "key": "x"}),
    ("42", {"key_repr": "42", "key": 42}),
    ("(1, 'x')", {"key_repr": "(1, 'x')"}),
    ("__import__('os').system('command')", {"key_repr": "__import__('os').system('command')"}),
])
def test_key_literals_never_execute(message, parameters) -> None:
    found = PythonAnalyzer().analyze(CONTEXT, ExecutionResult(1),
                                     CapturedData(stderr=HEADER + "KeyError: " + message))
    assert found[0].parameters == parameters


def test_no_guessed_parameters_or_locations() -> None:
    diagnostic = PythonAnalyzer().analyze(CONTEXT, ExecutionResult(1),
        CapturedData(stderr=HEADER + "ModuleNotFoundError: something custom"))[0]
    assert diagnostic.parameters == {}
    assert diagnostic.file_path == "main.py"  # a reported frame, not guessed ownership
    assert rule_id_for("pkg.CustomError") is None
    assert rule_id_for("TabError") == "python.tab_error"
    assert len(RULE_IDS) == 11


def test_syntax_error_inside_runtime_traceback() -> None:
    text = HEADER + '  File "generated.py", line 8\n    x =\n       ^\nSyntaxError: invalid syntax'
    found = PythonAnalyzer().analyze(CONTEXT, ExecutionResult(1), CapturedData(stderr=text))
    assert found[0].file_path == "generated.py" and len(found[0].frames) == 2
    assert found[0].parameters["caret_column"] == 4


def test_unterminated_message_and_damaged_frame_are_incomplete() -> None:
    analyzer = PythonAnalyzer()
    for text in (HEADER + "TypeError: partial", TRACEBACK.replace("main.py", "bad\ufffd.py")):
        found = analyzer.analyze(CONTEXT, ExecutionResult(1), CapturedData(stderr=text))
        assert len(found) == 1 and found[0].incomplete


def test_group_without_closing_border_is_incomplete() -> None:
    text = next(case["text"] for case in CORPUS if case["name"] == "group")
    text = text.rsplit("    +------------------------------------", 1)[0]
    found = PythonAnalyzer().analyze(CONTEXT, ExecutionResult(1), CapturedData(stderr=text))
    assert len(found) == 1 and found[0].complex_structure and found[0].incomplete


def test_analyzer_is_silent(capsys: pytest.CaptureFixture[str]) -> None:
    PythonAnalyzer().analyze(CONTEXT, ExecutionResult(1), CapturedData(stderr=TRACEBACK))
    assert capsys.readouterr() == ("", "")
