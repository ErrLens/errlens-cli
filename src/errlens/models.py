"""JSON-friendly contracts; messages remain identifiers until rendering.

Paths are strings so dataclasses.asdict results can be JSON-encoded directly.
Environment metadata is explicitly supplied context, not an environment dump.
"""

from dataclasses import dataclass, field
from typing import TypeAlias

Parameter: TypeAlias = str | int | float | bool | None


@dataclass
class ExecutionContext:
    """Executable plus arguments, working directory and capture provenance."""

    command: list[str]
    cwd: str
    capture_source: str = "runner"
    environment: dict[str, Parameter] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.command or not self.command[0]:
            raise ValueError("command must contain a nonempty executable")
        if not self.cwd or not self.capture_source:
            raise ValueError("cwd and capture_source must not be empty")


@dataclass
class ExecutionResult:
    """None means no exit status is available; negative POSIX signals are allowed.

    output_complete describes the diagnostic copy (false when capture truncates),
    not whether all bytes were forwarded. Forwarding failures raise RunnerError.
    """

    exit_code: int | None
    interrupted: bool = False
    output_complete: bool = True


@dataclass
class StackFrame:
    """Location reported by Python; no claim that it belongs to user code."""

    file_path: str
    line_number: int | None = None
    function: str | None = None

    def __post_init__(self) -> None:
        if self.line_number is not None and self.line_number < 1:
            raise ValueError("line_number must be positive or None")


@dataclass
class Diagnostic:
    """Observed error facts, never a localized explanation or guessed cause."""

    diagnostic_id: str
    error_type: str
    original_message: str
    file_path: str | None = None
    line_number: int | None = None
    parameters: dict[str, Parameter] = field(default_factory=dict)
    incomplete: bool = False
    frames: list[StackFrame] = field(default_factory=list)
    source: str | None = None
    chain_relation: str | None = None
    related_diagnostic_id: str | None = None
    complex_structure: bool = False
    execution_failed: bool | None = None

    def __post_init__(self) -> None:
        if not self.diagnostic_id or not self.error_type:
            raise ValueError("diagnostic_id and error_type must not be empty")
        if self.line_number is not None and self.line_number < 1:
            raise ValueError("line_number must be positive or None")


@dataclass
class SuggestedCommand:
    """Display-only argv from trusted rules, guarded by a localized condition."""

    argv: list[str]
    condition_id: str


@dataclass
class Explanation:
    """Rule output. Actions, possible causes and conditions are message IDs.

    message_ids maps semantic roles (such as 'problem') to translation keys.
    actions lists suggested-action message IDs; conditions lists applicability
    message IDs for the recommendations as a whole. commands holds separate
    display-only argv with explicit applicability. No execution is implied.
    """

    rule_id: str
    message_ids: dict[str, str]
    parameters: dict[str, Parameter] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    causes: list[str] = field(default_factory=list)
    commands: list[SuggestedCommand] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.rule_id or not self.message_ids:
            raise ValueError("rule_id and message_ids must not be empty")
        if any(not role or not key for role, key in self.message_ids.items()):
            raise ValueError("message roles and IDs must not be empty")


@dataclass
class ExplanationReport:
    """One primary diagnostic with its actual linked predecessors."""

    diagnostic: Diagnostic
    explanation: Explanation
    related: list[Diagnostic] = field(default_factory=list)
    other_count: int = 0
