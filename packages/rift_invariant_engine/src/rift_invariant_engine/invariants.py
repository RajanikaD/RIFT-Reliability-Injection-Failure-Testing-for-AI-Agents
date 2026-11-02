"""Small reusable invariants driven by explicit typed selectors."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sized
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, JsonValue

from rift_core import InvariantResult, InvariantStatus
from rift_invariant_engine.contracts import InvariantEvaluationContext

StateT = TypeVar("StateT")
ValueT = TypeVar("ValueT")

EvidenceSelector = Callable[[InvariantEvaluationContext[StateT]], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class FieldEqualsInvariant(Generic[StateT, ValueT]):
    """Require an explicitly selected value to equal an expected value."""

    name: str
    description: str
    selector: Callable[[InvariantEvaluationContext[StateT]], ValueT]
    expected: ValueT
    evidence_selector: EvidenceSelector[StateT] | None = None

    def evaluate(self, context: InvariantEvaluationContext[StateT]) -> InvariantResult:
        observed = self.selector(context)
        passed = observed == self.expected
        return _comparison_result(
            name=self.name,
            description=self.description,
            passed=passed,
            expected=self.expected,
            observed=observed,
            evidence=_select_evidence(self.evidence_selector, context),
        )


@dataclass(frozen=True, slots=True)
class CountEqualsInvariant(Generic[StateT]):
    """Require an explicitly selected collection to have an exact size."""

    name: str
    description: str
    selector: Callable[[InvariantEvaluationContext[StateT]], Sized]
    expected: int
    evidence_selector: EvidenceSelector[StateT] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.expected, bool) or self.expected < 0:
            raise ValueError("expected count must be a non-negative integer")

    def evaluate(self, context: InvariantEvaluationContext[StateT]) -> InvariantResult:
        observed = len(self.selector(context))
        return _comparison_result(
            name=self.name,
            description=self.description,
            passed=observed == self.expected,
            expected=self.expected,
            observed=observed,
            evidence=_select_evidence(self.evidence_selector, context),
        )


@dataclass(frozen=True, slots=True)
class NumericEqualsInvariant(Generic[StateT]):
    """Require an explicitly selected exact integer or Decimal value."""

    name: str
    description: str
    selector: Callable[[InvariantEvaluationContext[StateT]], int | Decimal]
    expected: int | Decimal
    evidence_selector: EvidenceSelector[StateT] | None = None

    def __post_init__(self) -> None:
        _require_exact_number(self.expected)

    def evaluate(self, context: InvariantEvaluationContext[StateT]) -> InvariantResult:
        observed = self.selector(context)
        _require_exact_number(observed)
        return _comparison_result(
            name=self.name,
            description=self.description,
            passed=observed == self.expected,
            expected=self.expected,
            observed=observed,
            evidence=_select_evidence(self.evidence_selector, context),
        )


@dataclass(frozen=True, slots=True)
class PredicateInvariant(Generic[StateT]):
    """Require an explicit predicate over the evaluation context to be true."""

    name: str
    description: str
    predicate: Callable[[InvariantEvaluationContext[StateT]], bool]
    evidence_selector: EvidenceSelector[StateT] | None = None

    def evaluate(self, context: InvariantEvaluationContext[StateT]) -> InvariantResult:
        observed = self.predicate(context)
        if not isinstance(observed, bool):
            raise TypeError("predicate must return bool")
        return _comparison_result(
            name=self.name,
            description=self.description,
            passed=observed,
            expected=True,
            observed=observed,
            evidence=_select_evidence(self.evidence_selector, context),
        )


def _comparison_result(
    *,
    name: str,
    description: str,
    passed: bool,
    expected: object,
    observed: object,
    evidence: dict[str, JsonValue],
) -> InvariantResult:
    status = InvariantStatus.PASS if passed else InvariantStatus.FAIL
    message = "Invariant satisfied." if passed else "Invariant not satisfied."
    return InvariantResult(
        invariant_id=name,
        description=description,
        status=status,
        message=message,
        expected=_to_json_value(expected),
        observed=_to_json_value(observed),
        evidence=evidence,
    )


def _select_evidence(
    selector: EvidenceSelector[StateT] | None,
    context: InvariantEvaluationContext[StateT],
) -> dict[str, JsonValue]:
    if selector is None:
        return {}
    return {key: _to_json_value(value) for key, value in selector(context).items()}


def _require_exact_number(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise TypeError("numeric invariant values must be int or Decimal")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("numeric invariant Decimal values must be finite")


def _to_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    if isinstance(value, BaseModel):
        return _to_json_value(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    raise TypeError(f"value is not JSON-compatible evidence: {type(value).__name__}")
