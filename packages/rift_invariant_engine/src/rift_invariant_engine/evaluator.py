"""Deterministic evaluator and transparent aggregate summary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, computed_field

from rift_core import InvariantResult, InvariantStatus
from rift_invariant_engine.contracts import Invariant, InvariantEvaluationContext

StateT = TypeVar("StateT")


class InvariantEvaluationSummary(BaseModel):
    """Ordered invariant results and unweighted aggregate counts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results: tuple[InvariantResult, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return len(self.results)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> int:
        return sum(result.status is InvariantStatus.PASS for result in self.results)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed(self) -> int:
        return sum(result.status is InvariantStatus.FAIL for result in self.results)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def errors(self) -> int:
        return sum(result.status is InvariantStatus.ERROR for result in self.results)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_passed(self) -> bool:
        return self.total > 0 and self.passed == self.total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def correctness_ratio(self) -> float:
        """Return passed / total; ERROR results remain in the denominator."""

        return self.passed / self.total if self.total else 0.0


class InvariantEvaluator(Generic[StateT]):
    """Evaluate independent invariants in configured order without fail-fast behavior."""

    def __init__(self, invariants: Sequence[Invariant[StateT]]) -> None:
        self._invariants = tuple(invariants)

    def evaluate(self, context: InvariantEvaluationContext[StateT]) -> InvariantEvaluationSummary:
        results: list[InvariantResult] = []
        for invariant in self._invariants:
            try:
                result = invariant.evaluate(context)
            except Exception as error:  # An evaluator error is evidence, not a suite abort.
                error_message = _describe_error(error)
                result = InvariantResult(
                    invariant_id=invariant.name,
                    description=invariant.description,
                    status=InvariantStatus.ERROR,
                    message="Invariant evaluation raised an unexpected error.",
                    evidence={"exception_type": type(error).__name__},
                    error=error_message,
                )
            results.append(result)
        return InvariantEvaluationSummary(results=tuple(results))


def _describe_error(error: Exception) -> str:
    message = str(error).strip()
    return f"{type(error).__name__}: {message}" if message else type(error).__name__
