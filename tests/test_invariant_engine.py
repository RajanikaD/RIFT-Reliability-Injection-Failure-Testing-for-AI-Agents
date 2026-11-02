from dataclasses import dataclass
from decimal import Decimal

from rift_core import InvariantResult, InvariantStatus
from rift_invariant_engine import (
    CountEqualsInvariant,
    FieldEqualsInvariant,
    InvariantEvaluationContext,
    InvariantEvaluator,
    NumericEqualsInvariant,
    PredicateInvariant,
)


def context() -> InvariantEvaluationContext[dict[str, object]]:
    return InvariantEvaluationContext(
        before_state={"status": "pending", "items": [1]},
        after_state={"status": "complete", "items": [1, 2]},
    )


def test_field_equals_invariant_passes_with_structured_evidence() -> None:
    invariant = FieldEqualsInvariant(
        name="status_complete",
        description="Status must be complete.",
        selector=lambda evaluation: evaluation.after_state["status"],
        expected="complete",
        evidence_selector=lambda _evaluation: {"resource_id": "resource-1"},
    )

    result = invariant.evaluate(context())

    assert result.status is InvariantStatus.PASS
    assert result.expected == "complete"
    assert result.observed == "complete"
    assert result.evidence == {"resource_id": "resource-1"}


def test_field_equals_invariant_fails() -> None:
    invariant = FieldEqualsInvariant(
        name="status_failed",
        description="Status must be failed.",
        selector=lambda evaluation: evaluation.after_state["status"],
        expected="failed",
    )

    assert invariant.evaluate(context()).status is InvariantStatus.FAIL


def test_count_equals_invariant_passes_and_fails() -> None:
    passing = CountEqualsInvariant(
        name="two_items",
        description="There must be two items.",
        selector=lambda evaluation: evaluation.after_state["items"],
        expected=2,
    )
    failing = CountEqualsInvariant(
        name="one_item",
        description="There must be one item.",
        selector=lambda evaluation: evaluation.after_state["items"],
        expected=1,
    )

    assert passing.evaluate(context()).status is InvariantStatus.PASS
    assert failing.evaluate(context()).status is InvariantStatus.FAIL


def test_numeric_equals_invariant_preserves_decimal_exactness() -> None:
    invariant = NumericEqualsInvariant(
        name="amount_matches",
        description="The exact decimal amount must match.",
        selector=lambda _evaluation: Decimal("79.99"),
        expected=Decimal("79.99"),
    )

    result = invariant.evaluate(context())

    assert result.status is InvariantStatus.PASS
    assert result.expected == "79.99"
    assert result.observed == "79.99"


def test_predicate_invariant_uses_an_explicit_context_predicate() -> None:
    invariant = PredicateInvariant(
        name="transitioned",
        description="The status must change.",
        predicate=lambda evaluation: (
            evaluation.before_state["status"] != evaluation.after_state["status"]
        ),
    )

    assert invariant.evaluate(context()).status is InvariantStatus.PASS


@dataclass(frozen=True)
class RaisingInvariant:
    name: str = "broken"
    description: str = "This invariant raises unexpectedly."

    def evaluate(self, _context: InvariantEvaluationContext[dict[str, object]]) -> InvariantResult:
        raise RuntimeError("selector crashed")


@dataclass(frozen=True)
class ErrorReturningInvariant:
    name: str = "explicit_error"
    description: str = "This invariant reports an evaluation error."

    def evaluate(self, _context: InvariantEvaluationContext[dict[str, object]]) -> InvariantResult:
        return InvariantResult(
            invariant_id=self.name,
            description=self.description,
            status=InvariantStatus.ERROR,
            message="Evaluation input was unavailable.",
            error="missing input",
        )


def test_evaluator_preserves_order_and_continues_after_failure_and_exception() -> None:
    failing = FieldEqualsInvariant(
        name="first_failure",
        description="This configured comparison fails.",
        selector=lambda evaluation: evaluation.after_state["status"],
        expected="failed",
    )
    passing = FieldEqualsInvariant(
        name="last_pass",
        description="This configured comparison passes.",
        selector=lambda evaluation: evaluation.after_state["status"],
        expected="complete",
    )
    evaluator = InvariantEvaluator([failing, RaisingInvariant(), passing])

    summary = evaluator.evaluate(context())

    assert [result.invariant_id for result in summary.results] == [
        "first_failure",
        "broken",
        "last_pass",
    ]
    assert [result.status for result in summary.results] == [
        InvariantStatus.FAIL,
        InvariantStatus.ERROR,
        InvariantStatus.PASS,
    ]
    assert summary.results[1].error == "RuntimeError: selector crashed"
    assert summary.results[1].evidence == {"exception_type": "RuntimeError"}


def test_evaluator_continues_after_an_explicit_error_result() -> None:
    passing = PredicateInvariant(
        name="still_runs",
        description="This invariant must still run.",
        predicate=lambda _evaluation: True,
    )

    summary = InvariantEvaluator([ErrorReturningInvariant(), passing]).evaluate(context())

    assert [result.status for result in summary.results] == [
        InvariantStatus.ERROR,
        InvariantStatus.PASS,
    ]


def test_summary_counts_errors_as_not_passed_and_in_ratio_denominator() -> None:
    invariants = [
        PredicateInvariant(
            name="pass",
            description="Passes.",
            predicate=lambda _evaluation: True,
        ),
        PredicateInvariant(
            name="fail",
            description="Fails.",
            predicate=lambda _evaluation: False,
        ),
        RaisingInvariant(),
    ]

    summary = InvariantEvaluator(invariants).evaluate(context())

    assert summary.total == 3
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.errors == 1
    assert summary.all_passed is False
    assert summary.correctness_ratio == 1 / 3


def test_summary_all_passed_requires_a_nonempty_all_pass_result() -> None:
    passing = PredicateInvariant(
        name="pass",
        description="Passes.",
        predicate=lambda _evaluation: True,
    )

    assert InvariantEvaluator([passing]).evaluate(context()).all_passed is True
    assert InvariantEvaluator([]).evaluate(context()).all_passed is False
