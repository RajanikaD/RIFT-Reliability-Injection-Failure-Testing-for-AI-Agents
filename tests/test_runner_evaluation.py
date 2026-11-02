import pytest

from rift_core import (
    AgentRunOutput,
    AgentStatus,
    InvariantResult,
    InvariantStatus,
    RunOutcome,
)
from rift_experiment_runner import OutcomeClassification, classify, derive_outcome, diff_states


def result(invariant_id: str, status: InvariantStatus) -> InvariantResult:
    return InvariantResult(
        invariant_id=invariant_id,
        description="d",
        status=status,
        message="m",
        error="boom" if status is InvariantStatus.ERROR else None,
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], RunOutcome.INCONCLUSIVE),
        ([InvariantStatus.PASS, InvariantStatus.PASS], RunOutcome.PASS),
        ([InvariantStatus.PASS, InvariantStatus.FAIL], RunOutcome.FAIL),
        ([InvariantStatus.FAIL, InvariantStatus.ERROR], RunOutcome.ERROR),
    ],
)
def test_outcome_is_derived_only_from_invariants(statuses, expected) -> None:
    results = [result(f"i{index}", status) for index, status in enumerate(statuses)]
    assert derive_outcome(results) is expected


@pytest.mark.parametrize(
    ("outcome", "agent_status", "expected"),
    [
        (RunOutcome.PASS, AgentStatus.COMPLETED, OutcomeClassification.CORRECT),
        (RunOutcome.PASS, AgentStatus.GAVE_UP, OutcomeClassification.UNCONFIRMED_SUCCESS),
        (RunOutcome.PASS, AgentStatus.CRASHED, OutcomeClassification.UNCONFIRMED_SUCCESS),
        (RunOutcome.FAIL, AgentStatus.COMPLETED, OutcomeClassification.SILENT_FAILURE),
        (RunOutcome.FAIL, AgentStatus.GAVE_UP, OutcomeClassification.DETECTED_FAILURE),
        (RunOutcome.ERROR, AgentStatus.COMPLETED, OutcomeClassification.EVALUATION_ERROR),
        (RunOutcome.INCONCLUSIVE, AgentStatus.COMPLETED, OutcomeClassification.EVALUATION_ERROR),
    ],
)
def test_classification_crosses_agent_claim_with_actual_outcome(
    outcome, agent_status, expected
) -> None:
    assert classify(outcome, AgentRunOutput(status=agent_status)) is expected


def test_state_diff_reports_added_removed_and_changed_values() -> None:
    baseline = {"refunds": [{"id": "R1"}], "stock": 10, "gone": True}
    faulted = {"refunds": [{"id": "R1"}, {"id": "R2"}], "stock": 11}

    differences = {item.path: item for item in diff_states(baseline, faulted)}

    assert set(differences) == {"gone", "refunds[1]", "stock"}
    assert differences["refunds[1]"].change == "added"
    assert differences["refunds[1]"].faulted == {"id": "R2"}
    assert differences["gone"].change == "removed"
    assert (differences["stock"].baseline, differences["stock"].faulted) == (10, 11)


def test_identical_states_have_no_differences() -> None:
    assert diff_states({"a": [1, {"b": None}]}, {"a": [1, {"b": None}]}) == ()
