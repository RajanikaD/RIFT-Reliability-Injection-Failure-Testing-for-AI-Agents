"""D1 regression tests: a run result cannot claim an outcome its invariants contradict.

The defect (Milestone 1 closeout, M1-D1): ``ExperimentRunResult.outcome`` was a free field. The
runner derived it correctly, but any other producer (a future API, a persisted record, a
hand-written fixture) could store ``PASS`` next to failing invariants and every consumer would
believe it. The rule now lives in ``rift_core`` and is enforced at validation time.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rift_core import (
    ExecutionContext,
    ExperimentRunResult,
    InvariantResult,
    InvariantStatus,
    RunMode,
    RunOutcome,
    derive_run_outcome,
)
from rift_experiment_runner import derive_outcome

CONTEXT = ExecutionContext(experiment_id="e", run_id="r", seed=0, run_mode=RunMode.BASELINE)


def result(status: InvariantStatus, invariant_id: str = "i") -> InvariantResult:
    return InvariantResult(
        invariant_id=invariant_id,
        description="d",
        status=status,
        message="m",
        error="boom" if status is InvariantStatus.ERROR else None,
    )


def test_pass_with_a_failing_invariant_is_rejected() -> None:
    with pytest.raises(ValidationError, match="contradicts"):
        ExperimentRunResult(
            context=CONTEXT,
            outcome=RunOutcome.PASS,
            invariant_results=(result(InvariantStatus.FAIL),),
        )


def test_fail_with_only_passing_invariants_is_rejected() -> None:
    with pytest.raises(ValidationError, match="contradicts"):
        ExperimentRunResult(
            context=CONTEXT,
            outcome=RunOutcome.FAIL,
            invariant_results=(result(InvariantStatus.PASS),),
        )


@pytest.mark.parametrize(
    ("statuses", "outcome"),
    [
        ((InvariantStatus.PASS,), RunOutcome.PASS),
        ((InvariantStatus.PASS, InvariantStatus.FAIL), RunOutcome.FAIL),
        ((InvariantStatus.FAIL, InvariantStatus.ERROR), RunOutcome.ERROR),
    ],
)
def test_consistent_outcomes_are_accepted(statuses, outcome) -> None:
    results = tuple(result(status, f"i{n}") for n, status in enumerate(statuses))
    assert ExperimentRunResult(context=CONTEXT, outcome=outcome, invariant_results=results)


@pytest.mark.parametrize("outcome", [RunOutcome.INCONCLUSIVE, RunOutcome.ERROR])
def test_without_invariant_results_only_inconclusive_or_error_are_allowed(outcome) -> None:
    assert ExperimentRunResult(context=CONTEXT, outcome=outcome)


@pytest.mark.parametrize("outcome", [RunOutcome.PASS, RunOutcome.FAIL])
def test_without_invariant_results_pass_or_fail_is_rejected(outcome) -> None:
    with pytest.raises(ValidationError, match="contradicts"):
        ExperimentRunResult(context=CONTEXT, outcome=outcome)


def test_runner_derivation_delegates_to_the_core_rule() -> None:
    results = [result(InvariantStatus.PASS, "a"), result(InvariantStatus.FAIL, "b")]
    assert derive_outcome(results) is derive_run_outcome(results) is RunOutcome.FAIL
