"""Rule facts, conditional advice, and display-only fixed command construction."""

from dataclasses import asdict
import os
import sys

import pytest

from errlens.capture import Capture
from errlens.i18n import Translator, load_catalog
from errlens.models import Diagnostic, ExecutionContext, ExecutionResult
from errlens.rules.python import RULE_IDS, explain
from errlens.service import explain_capture

CONTEXT = ExecutionContext([sys.executable, "main.py"], ".")


@pytest.mark.parametrize("error_type", list(RULE_IDS))
@pytest.mark.parametrize("locale", ["ru", "en"])
def test_all_supported_explanations(error_type: str, locale: str) -> None:
    diagnostic = Diagnostic("test", error_type, "original")
    before = asdict(diagnostic)
    result = explain(diagnostic, CONTEXT)
    translator, catalog = Translator(locale), load_catalog(locale)
    keys = [*result.message_ids.values(), *result.causes, *result.actions, *result.conditions]
    assert result.rule_id == RULE_IDS[error_type]
    assert result.actions and result.conditions and result.causes
    for key in keys:
        assert key in catalog
        assert translator.translate(key, **result.parameters)
    assert asdict(diagnostic) == before
    assert result.commands == []


@pytest.mark.parametrize("module", ["os", "sys", "PIL", "my_local_module", "requests.sessions",
                                    "requests; touch bad", "requests\n--evil", "[red]requests",
                                    "requests$(command)", "requests' --index-url evil"])
def test_untrusted_or_ambiguous_modules_never_become_commands(module: str) -> None:
    result = explain(Diagnostic("id", "ModuleNotFoundError", "missing", parameters={"module_name": module}), CONTEXT)
    assert result.commands == []


def test_requests_command_uses_target_not_errlens_runtime(tmp_path) -> None:
    executable = str(tmp_path / "a different environment" / ("python.exe" if os.name == "nt" else "python"))
    context = ExecutionContext([executable, "main.py"], ".")
    result = explain(Diagnostic("id", "ModuleNotFoundError", "missing", parameters={"module_name": "requests"}), context)
    assert len(result.commands) == 1
    assert result.commands[0].argv == [executable, "-m", "pip", "install", "requests"]
    assert result.commands[0].condition_id == "command.install_condition"


@pytest.mark.parametrize("command", [["python", "main.py"], ["py", "-3", "main.py"],
                                      [sys.executable, "-I", "main.py"],
                                      [sys.executable, "-S", "main.py"]])
def test_unknown_or_modified_interpreter_environment_has_no_command(command) -> None:
    result = explain(Diagnostic("id", "ModuleNotFoundError", "missing", parameters={"module_name": "requests"}),
                     ExecutionContext(command, "."))
    assert not result.commands


def test_incomplete_and_unknown_do_not_infer_causes() -> None:
    incomplete = explain(Diagnostic("id", "ModuleNotFoundError", "", incomplete=True,
                                    parameters={"module_name": "requests"}), CONTEXT)
    unknown = explain(Diagnostic("id", "CustomProblem", "custom"), CONTEXT)
    assert incomplete.rule_id == "python.incomplete"
    assert unknown.rule_id == "python.unknown"
    assert not incomplete.causes and not incomplete.commands
    assert not unknown.causes and not unknown.commands


def test_no_context_free_pip_or_admin_advice() -> None:
    for locale in ("ru", "en"):
        translator = Translator(locale)
        permission = explain(Diagnostic("id", "PermissionError", "denied"), CONTEXT)
        assert permission.commands == []
        text = " ".join(translator.translate(key) for key in permission.actions)
        assert "sudo" not in text and "Run as administrator" not in text


def test_service_selects_final_and_links_predecessor() -> None:
    capture = Capture()
    capture.append("stderr", (
        'Traceback (most recent call last):\n  File "a.py", line 1\nKeyError: \'root\'\n\n'
        'The above exception was the direct cause of the following exception:\n\n'
        'Traceback (most recent call last):\n  File "b.py", line 2\nTypeError: final\n'
    ).encode())
    report = explain_capture(CONTEXT, ExecutionResult(1), capture)
    assert report.diagnostic.error_type == "TypeError"
    assert [item.error_type for item in report.related] == ["KeyError"]
    assert report.other_count == 0
    assert explain_capture(CONTEXT, ExecutionResult(0), capture) is None
    assert explain_capture(CONTEXT, ExecutionResult(1, interrupted=True), capture) is None


def test_independent_diagnostics_are_not_causes() -> None:
    capture = Capture()
    capture.append("stderr", ('Traceback (most recent call last):\n  File "a.py", line 1\nKeyError: \'a\'\n'
                              'Traceback (most recent call last):\n  File "b.py", line 2\nNameError: bad\n').encode())
    report = explain_capture(CONTEXT, ExecutionResult(1), capture)
    assert report.other_count == 1 and not report.related
