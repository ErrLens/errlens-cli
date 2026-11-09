"""Conservative parser for CPython's text traceback format, without I/O.

This recognizes diagnostic *text*, not proof of an unhandled exception. A caller
can distinguish a failed execution using Diagnostic.execution_failed. No source
files, imports, commands, translations or explanation rules are consulted.
"""

import ast
from dataclasses import dataclass, field
import re

from errlens.capture import CapturedData
from errlens.models import Diagnostic, ExecutionContext, ExecutionResult, Parameter, StackFrame

_HEADER = "Traceback (most recent call last):"
_GROUP_HEADER = "Exception Group Traceback (most recent call last):"
_CHAINS = {
    "During handling of the above exception, another exception occurred:": "context",
    "The above exception was the direct cause of the following exception:": "cause",
}
_SYNTAX = {"SyntaxError", "IndentationError", "TabError"}
_FRAME = re.compile(r'^  File "(?P<path>.+)", line (?P<line>[0-9]+)(?:, in (?P<function>.+))?$')
_NO_LINE_FRAME = re.compile(r'^  File "(?P<path>.+)"(?:, in (?P<function>.+))?$')
_TYPE = r"[^\W\d]\w*(?:\.[^\W\d]\w*)*"
_EXCEPTION = re.compile(rf"^(?P<type>{_TYPE})(?::(?: (?P<message>.*))?)?$")
_PYTHON_COMMAND = re.compile(r"(?:py|python(?:w)?(?:[0-9]+(?:\.[0-9]+)*)?|pypy(?:[0-9]+)?)", re.I)
_ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")


def _python_context(context: ExecutionContext) -> bool:
    name = context.command[0].replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return bool(_PYTHON_COMMAND.fullmatch(name)) or context.environment.get("language") == "python"


def _frame(line: str) -> StackFrame | None:
    match = _FRAME.fullmatch(line)
    if match:
        # Refuse oversized or invalid line numbers rather than raising on input.
        number = match["line"]
        if len(number) > 9 or int(number) < 1:
            return None
        return StackFrame(match["path"], int(number), match["function"])
    match = _NO_LINE_FRAME.fullmatch(line)
    if match:
        return StackFrame(match["path"], function=match["function"])
    return None


def _parameters(error_type: str, message: str) -> dict[str, Parameter]:
    """Extract only explicit scalar values; never infer a package or a fix."""
    parameters: dict[str, Parameter] = {}
    patterns = {
        "ModuleNotFoundError": (r"^No module named '([^']+)'(?:; .*)?$", ("module_name",)),
        "ImportError": (r"^cannot import name '([^']+)'(?: from .*)?$", ("import_name",)),
        "NameError": (r"^name '([^']+)' is not defined(?:\..*)?$", ("name",)),
        "AttributeError": (r"^'([^']+)' object has no attribute '([^']+)'(?:\..*)?$",
                           ("object_type", "attribute_name")),
    }
    base_type = error_type.rsplit(".", 1)[-1]
    if base_type in patterns:
        pattern, names = patterns[base_type]
        match = re.fullmatch(pattern, message.split("\n", 1)[0])
        if match:
            parameters.update(zip(names, match.groups()))
    if base_type == "AttributeError" and not parameters:
        match = re.fullmatch(r"module '([^']+)' has no attribute '([^']+)'(?:\..*)?", message)
        if match:
            parameters.update(module_name=match[1], attribute_name=match[2])
        else:
            match = re.fullmatch(r"type object '([^']+)' has no attribute '([^']+)'(?:\..*)?", message)
            if match:
                parameters.update(object_type=match[1], attribute_name=match[2])
    if base_type == "KeyError":
        parameters["key_repr"] = message
        # Literal evaluation is limited and scalar-only, not arbitrary execution.
        if len(message) <= 4096:
            try:
                value = ast.literal_eval(message)
            except (ValueError, SyntaxError, RecursionError, MemoryError):
                pass
            else:
                if value is None or isinstance(value, (str, int, float, bool)):
                    parameters["key"] = value
    if base_type in {"FileNotFoundError", "PermissionError"}:
        match = re.fullmatch(r"\[Errno ([0-9]+)\] [^\n]*?: (.+)", message)
        if match:
            parameters["errno"] = int(match[1]) if len(match[1]) < 10 else None
            # A rename error can contain two repr paths. Do not pick one as fact.
            path_repr = match[2]
            if len(path_repr) <= 4096:
                try:
                    path = ast.literal_eval(path_repr)
                except (ValueError, SyntaxError, RecursionError, MemoryError):
                    pass
                else:
                    if isinstance(path, str):
                        parameters["file_path"] = path
    return parameters


@dataclass
class _Block:
    has_header: bool
    complex_structure: bool = False
    frames: list[StackFrame] = field(default_factory=list)
    error_type: str | None = None
    messages: list[str] = field(default_factory=list)
    caret_column: int | None = None
    caret_end_column: int | None = None
    damaged: bool = False
    relation: str | None = None
    related_id: str | None = None


class PythonAnalyzer:
    """Recognize strong stderr structure; stdout also requires failed Python context.

    Bare 'SomeError: text' lines are deliberately insufficient. Headerless tail
    recovery requires known truncation and Python context, except compiler-style
    syntax diagnostics which naturally have no traceback header.
    """

    analyzer_id = "python"

    def analyze(
        self, context: ExecutionContext, result: ExecutionResult, data: CapturedData,
    ) -> list[Diagnostic]:
        python = _python_context(context)
        failed = result.exit_code != 0 if result.exit_code is not None else None
        diagnostics: list[Diagnostic] = []
        # Preserve stream-local order. There is no reliable order across streams.
        sources = [("stderr", data.stderr, data.stderr_truncated),
                   ("stdout", data.stdout, data.stdout_truncated)]
        if data.combined is not None:
            sources.append(("combined", data.combined, data.combined_truncated))
        for source, text, truncated in sources:
            if source != "stderr" and not (python and failed and not result.interrupted):
                continue
            diagnostics.extend(self._parse(text, source, python, failed,
                                           truncated or not result.output_complete))
        return diagnostics

    def _parse(
        self, text: str, source: str, python: bool, failed: bool | None, truncated: bool,
    ) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        block: _Block | None = None
        relation: str | None = None
        related_id: str | None = None
        in_group_tree = False
        group_diagnostic: Diagnostic | None = None
        # A terminal may append VT mode/cursor resets after the final newline.
        # Determine completeness from diagnostic text, not transport controls.
        text = _ANSI.sub("", text)
        unterminated = bool(text) and not text.endswith(("\n", "\r"))

        def finish() -> None:
            nonlocal block
            if block is None:
                return
            base = (block.error_type or "").rsplit(".", 1)[-1]
            syntax = base in _SYNTAX
            supported_structure = block.has_header or (python and (syntax or truncated))
            if block.frames and supported_structure:
                message = "\n".join(block.messages).rstrip("\n")
                error_type = block.error_type or "UnknownPythonException"
                parameters = _parameters(error_type, message)
                if syntax and block.caret_column is not None:
                    parameters["caret_column"] = block.caret_column
                    parameters["caret_end_column"] = block.caret_end_column
                location = block.frames[-1]
                diagnostics.append(Diagnostic(
                    diagnostic_id=f"python.{source}.{len(diagnostics) + 1}",
                    error_type=error_type, original_message=message,
                    file_path=location.file_path, line_number=location.line_number,
                    parameters=parameters,
                    incomplete=(truncated or unterminated or block.damaged or block.error_type is None
                                or (not block.has_header and not syntax)),
                    frames=block.frames, source=source, chain_relation=block.relation,
                    related_diagnostic_id=block.related_id,
                    complex_structure=block.complex_structure, execution_failed=failed,
                ))
            block = None

        # splitlines/ANSI work only on the bounded diagnostic copy from Capture.
        for line in text.splitlines():
            group_header = line.strip().lstrip("+ ") == _GROUP_HEADER
            if line == _HEADER or group_header:
                finish()
                block = _Block(True, group_header, relation=relation, related_id=related_id)
                relation = related_id = None
                in_group_tree = False
                continue
            if line in _CHAINS:
                finish()
                relation = _CHAINS[line] if diagnostics else None
                related_id = diagnostics[-1].diagnostic_id if diagnostics else None
                in_group_tree = False
                continue
            if in_group_tree:
                # Never misreport nested frames as independent top-level failures.
                if re.fullmatch(r"    \+-{3,}", line) and group_diagnostic is not None:
                    group_diagnostic.incomplete = truncated or unterminated
                    group_diagnostic = None
                if line.startswith("  ") or not line:
                    continue
                in_group_tree = False
            if block is not None and block.complex_structure and line.startswith("  | "):
                line = line[4:]
            frame = _frame(line)
            if frame is not None:
                if block is not None and block.error_type is not None:
                    finish()
                if block is None:
                    block = _Block(False, relation=relation, related_id=related_id)
                    relation = related_id = None
                if "\ufffd" in line or "\x1b" in line or "\x00" in line:
                    block.damaged = True
                block.frames.append(frame)
                block.caret_column = block.caret_end_column = None
                continue
            if block is None:
                if line.strip():
                    relation = related_id = None
                continue
            if "\ufffd" in line or "\x1b" in line or "\x00" in line:
                block.damaged = True
            if block.error_type is not None:
                block.messages.append(line)
                continue
            match = _EXCEPTION.fullmatch(line)
            if match and block.frames:
                block.error_type = match["type"]
                block.messages.append(match["message"] or "")
                if block.complex_structure:
                    damaged = block.damaged
                    count = len(diagnostics)
                    finish()
                    if len(diagnostics) > count:
                        group_diagnostic = diagnostics[-1]
                        # A missing outer closing border indicates an unfinished tree.
                        group_diagnostic.incomplete = True
                        if damaged:
                            group_diagnostic = None  # closing border cannot repair damaged text
                    in_group_tree = True
                continue
            if line.startswith("    ") and "^" in line and set(line.strip()) <= set("^~ \t"):
                # One-based column in the *displayed* source, not SyntaxError.offset.
                block.caret_column = line.index("^") - 4 + 1
                block.caret_end_column = line.rindex("^") - 4 + 2
            elif line.startswith("  File "):
                block.damaged = True
            elif line and not line.startswith(" "):
                # Unstructured text cannot complete an unfinished traceback.
                block.damaged = True
        finish()
        return diagnostics
