"""Post-execution analysis/explanation coordination, without process or terminal I/O."""

from errlens.analyzers.base import AnalyzerRegistry
from errlens.analyzers.python import PythonAnalyzer
from errlens.capture import Capture
from errlens.models import Diagnostic, ExecutionContext, ExecutionResult, ExplanationReport
from errlens.rules.python import explain


def analyze_capture(
    context: ExecutionContext, result: ExecutionResult, capture: Capture,
    *, registry: AnalyzerRegistry | None = None, encoding: str = "utf-8",
) -> list[Diagnostic]:
    """Analyze bounded tails once the runner has finished. Inputs are not modified.

    Callers can inspect structured results without reparsing the original bytes.
    """
    if registry is None:
        registry = AnalyzerRegistry()
        registry.register(PythonAnalyzer())
    data = capture.decoded(encoding)
    diagnostics: list[Diagnostic] = []
    for analyzer in registry.all():
        diagnostics.extend(analyzer.analyze(context, result, data))
    return diagnostics


def explain_capture(
    context: ExecutionContext, result: ExecutionResult, capture: Capture,
    *, registry: AnalyzerRegistry | None = None, encoding: str = "utf-8",
) -> ExplanationReport | None:
    """One report after a failed, non-interrupted execution; no output on success.

    Prefer stderr, then combined, then stdout. Follow explicit chain links only;
    independent diagnostics are counted, never labelled as causes.
    """
    if result.exit_code in (0, None) or result.interrupted:
        return None
    diagnostics = analyze_capture(context, result, capture, registry=registry, encoding=encoding)
    if not diagnostics:
        return None
    primary = next((items[-1] for source in ("stderr", "combined", "stdout")
                    if (items := [item for item in diagnostics if item.source == source])),
                   diagnostics[-1])
    indexed = {item.diagnostic_id: item for item in diagnostics}
    related: list[Diagnostic] = []
    seen = {primary.diagnostic_id}
    current = primary
    while current.related_diagnostic_id and current.related_diagnostic_id not in seen:
        predecessor = indexed.get(current.related_diagnostic_id)
        if predecessor is None:
            break
        related.append(predecessor)
        seen.add(predecessor.diagnostic_id)
        current = predecessor
    related.reverse()
    return ExplanationReport(primary, explain(primary, context), related,
                             max(0, len(diagnostics) - len(related) - 1))
