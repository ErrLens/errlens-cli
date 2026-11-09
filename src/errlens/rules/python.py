"""Locale-independent explanation rules. Commands are display-only fixed argv."""

import os
import re
from types import MappingProxyType
from typing import Mapping
import unicodedata

from errlens.models import Diagnostic, ExecutionContext, Explanation, SuggestedCommand

RULE_IDS: Mapping[str, str] = MappingProxyType({
    "ModuleNotFoundError": "python.module_not_found",
    "ImportError": "python.import_error",
    "SyntaxError": "python.syntax_error",
    "IndentationError": "python.indentation_error",
    "TabError": "python.tab_error",
    "NameError": "python.name_error",
    "TypeError": "python.type_error",
    "AttributeError": "python.attribute_error",
    "KeyError": "python.key_error",
    "FileNotFoundError": "python.file_not_found",
    "PermissionError": "python.permission_error",
})


def rule_id_for(error_type: str) -> str | None:
    """Unknown/custom types have no rule; do not guess their inheritance."""
    return RULE_IDS.get(error_type)


# Exact imports only. Do not infer distribution names or strip module suffixes.
_PACKAGES = MappingProxyType({"requests": "requests"})
_PYTHON_EXECUTABLE = re.compile(r"(?:pythonw?|python[0-9]+(?:\.[0-9]+)*|pypy[0-9]*)", re.I)


def _known_interpreter(context: ExecutionContext) -> str | None:
    executable = context.command[0]
    name = os.path.basename(executable)
    if name.lower().endswith(".exe"):
        name = name[:-4]
    if len(executable) > 1024 or not os.path.isabs(executable) or not _PYTHON_EXECUTABLE.fullmatch(name):
        return None
    if any(unicodedata.category(character).startswith("C") for character in executable):
        return None
    # Avoid promising the same import environment with isolation/site flags.
    if len(context.command) > 1 and context.command[1].startswith("-"):
        if context.command[1] not in {"-c", "-m"}:
            return None
    return executable


def explain(diagnostic: Diagnostic, context: ExecutionContext) -> Explanation:
    """Explain known facts; unknown/incomplete types receive neutral notices."""
    if diagnostic.incomplete:
        rule = "python.incomplete"
    elif diagnostic.complex_structure or diagnostic.error_type in {"ExceptionGroup", "BaseExceptionGroup"}:
        rule = "python.exception_group"
    else:
        rule = rule_id_for(diagnostic.error_type) or "python.unknown"
    explanation = Explanation(
        rule, {"title": f"{rule}.title", "description": f"{rule}.description"},
        parameters={**diagnostic.parameters, "error_type": diagnostic.error_type},
        actions=[f"{rule}.action"], conditions=[f"{rule}.condition"],
    )
    # The possible-cause sentence is explicitly hypothetical, never a diagnosis.
    if rule in RULE_IDS.values():
        explanation.causes.append(f"{rule}.cause")
    detail_fields = {
        "ModuleNotFoundError": "module_name", "ImportError": "import_name",
        "NameError": "name", "AttributeError": "attribute_name", "KeyError": "key_repr",
        "FileNotFoundError": "file_path", "PermissionError": "file_path",
    }
    detail = detail_fields.get(diagnostic.error_type)
    if detail and detail in diagnostic.parameters and not diagnostic.incomplete:
        explanation.message_ids["detail"] = f"detail.{detail}"
    module = diagnostic.parameters.get("module_name")
    interpreter = _known_interpreter(context)
    if (rule == "python.module_not_found" and isinstance(module, str)
            and module in _PACKAGES and interpreter is not None):
        explanation.commands.append(SuggestedCommand(
            [interpreter, "-m", "pip", "install", _PACKAGES[module]],
            "command.install_condition",
        ))
    return explanation
