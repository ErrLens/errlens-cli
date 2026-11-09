"""Validate serializable contracts and independent mutable defaults."""

import json
from dataclasses import asdict

import pytest

from errlens.capture import CapturedData
from errlens.models import Diagnostic, ExecutionContext, ExecutionResult, Explanation


def test_models_are_json_serializable() -> None:
    models = [
        ExecutionContext(["python", "main.py"], "C:/проект", environment={"venv": True}),
        ExecutionResult(1, interrupted=False, output_complete=False),
        Diagnostic("python.name", "NameError", "unknown", "main.py", 3, {"name": "x"}),
        Explanation("python.name", {"problem": "name.problem"}, {"name": "x"},
                    ["name.check"], ["name.condition"]),
        CapturedData(stderr="ошибка", combined=None),
    ]
    for model in models:
        assert json.loads(json.dumps(asdict(model))) == asdict(model)


@pytest.mark.parametrize("command", [[], [""]])
def test_context_requires_executable(command: list[str]) -> None:
    with pytest.raises(ValueError):
        ExecutionContext(command, ".")


@pytest.mark.parametrize("line", [0, -1])
def test_diagnostic_rejects_invalid_line(line: int) -> None:
    with pytest.raises(ValueError):
        Diagnostic("id", "NameError", "message", line_number=line)


def test_optional_fields_and_signal_status() -> None:
    assert ExecutionResult(None).exit_code is None
    assert ExecutionResult(-2, interrupted=True).interrupted
    assert Diagnostic("id", "Error", "message").file_path is None


def test_defaults_are_independent() -> None:
    first = ExecutionContext(["python"], ".")
    second = ExecutionContext(["python"], ".")
    first.environment["x"] = "value"
    assert second.environment == {}
    first_explanation = Explanation("a", {"problem": "a.problem"})
    second_explanation = Explanation("b", {"problem": "b.problem"})
    first_explanation.actions.append("a.action")
    assert second_explanation.actions == []


def test_explanation_requires_message_ids() -> None:
    with pytest.raises(ValueError):
        Explanation("rule", {})
