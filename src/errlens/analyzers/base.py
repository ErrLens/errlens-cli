"""Pure analyzer contract and explicit, instance-scoped internal registry."""

from typing import Protocol

from errlens.capture import CapturedData
from errlens.models import Diagnostic, ExecutionContext, ExecutionResult


class Analyzer(Protocol):
    """Inspect supplied data only: no output, translation, commands or writes."""

    @property
    def analyzer_id(self) -> str:
        """Stable identifier unique within a registry."""
        ...

    def analyze(
        self,
        context: ExecutionContext,
        result: ExecutionResult,
        data: CapturedData,
    ) -> list[Diagnostic]:
        """Return observations; return an empty list when nothing is recognized."""
        ...


class AnalyzerRegistry:
    """Register trusted analyzer instances in deterministic insertion order."""

    def __init__(self) -> None:
        self._analyzers: dict[str, Analyzer] = {}

    def register(self, analyzer: Analyzer) -> None:
        identifier = analyzer.analyzer_id
        if not identifier:
            raise ValueError("analyzer_id must not be empty")
        if identifier in self._analyzers:
            raise ValueError(f"Analyzer already registered: {identifier}")
        self._analyzers[identifier] = analyzer

    def get(self, analyzer_id: str) -> Analyzer:
        return self._analyzers[analyzer_id]

    def all(self) -> tuple[Analyzer, ...]:
        return tuple(self._analyzers.values())
