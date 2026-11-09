"""The registry has no implicit analyzers or global mutable state."""

import pytest

from errlens.analyzers.base import AnalyzerRegistry
from errlens.capture import CapturedData
from errlens.models import Diagnostic, ExecutionContext, ExecutionResult


class SampleAnalyzer:
    analyzer_id = "sample"

    def analyze(self, context: ExecutionContext, result: ExecutionResult,
                data: CapturedData) -> list[Diagnostic]:
        return [Diagnostic("sample.error", "ExampleError", data.stderr)]


def test_registry_and_contract() -> None:
    registry = AnalyzerRegistry()
    analyzer = SampleAnalyzer()
    registry.register(analyzer)
    assert registry.all() == (analyzer,)
    diagnostics = registry.get("sample").analyze(
        ExecutionContext(["example"], "."), ExecutionResult(1), CapturedData(stderr="example")
    )
    assert diagnostics[0].original_message == "example"
    assert AnalyzerRegistry().all() == ()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(analyzer)
    with pytest.raises(KeyError):
        registry.get("missing")


def test_registry_rejects_empty_id() -> None:
    analyzer = SampleAnalyzer()
    analyzer.analyzer_id = ""
    with pytest.raises(ValueError):
        AnalyzerRegistry().register(analyzer)
