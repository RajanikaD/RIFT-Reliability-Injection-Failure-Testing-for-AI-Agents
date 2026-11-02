"""End-to-end proofs for the commerce slice: agent -> gateway -> faults -> state -> verdict."""

import asyncio

import pytest

from commerce_demo.agents import AGENT_PROFILES
from commerce_demo.fault_cases import FAULT_CASES
from commerce_demo.scenario import CommerceScenarioBinding, commerce_experiment
from rift_core import InvariantStatus, RunOutcome
from rift_experiment_runner import (
    ComparisonVerdict,
    ExperimentReport,
    ExperimentRunner,
    OutcomeClassification,
)


class NoSleep:
    async def sleep(self, seconds: float) -> None:
        return None


def run(agent: str, fault_case: str) -> ExperimentReport:
    experiment = commerce_experiment(f"{agent}--{fault_case}", FAULT_CASES[fault_case].rules)
    runner = ExperimentRunner(sleeper=NoSleep())
    return asyncio.run(runner.run(experiment, CommerceScenarioBinding(), AGENT_PROFILES[agent]()))


def statuses(report: ExperimentReport) -> dict[str, InvariantStatus]:
    return {r.invariant_id: r.status for r in report.faulted.result.invariant_results}


def calls(report: ExperimentReport, tool_name: str):
    return [i for i in report.faulted.result.tool_invocations if i.tool_name == tool_name]


def final_state(report: ExperimentReport):
    assert report.faulted.result.state_snapshot is not None
    return report.faulted.result.state_snapshot.state


def test_successful_recovery_after_timeout_before_call() -> None:
    report = run("idempotent", "refund-timeout-before-call")
    refunds = calls(report, "refund_payment")

    assert [i.underlying_operation_executed for i in refunds] == [False, True]
    assert report.comparison.verdict is ComparisonVerdict.RESILIENT
    assert report.faulted.classification is OutcomeClassification.CORRECT


def test_failed_recovery_unsafe_retry_after_commit_duplicates_refund() -> None:
    report = run("retrying", "refund-timeout-after-commit")
    refunds = calls(report, "refund_payment")

    assert [i.underlying_operation_committed for i in refunds] == [True, None]
    assert len(final_state(report)["refunds"]) == 2
    assert statuses(report)["exactly_one_refund"] is InvariantStatus.FAIL
    assert report.comparison.verdict is ComparisonVerdict.DEGRADED
    assert report.faulted.classification is OutcomeClassification.SILENT_FAILURE


def test_partial_completion_is_detected_when_dependency_stays_down() -> None:
    report = run("retrying", "refund-outage")

    assert statuses(report) == {
        "order_cancelled": InvariantStatus.PASS,
        "exactly_one_refund": InvariantStatus.FAIL,
        "refund_amount_correct": InvariantStatus.FAIL,
        "inventory_restored": InvariantStatus.FAIL,
        "single_confirmation": InvariantStatus.FAIL,
        "refund_after_cancellation": InvariantStatus.PASS,  # no refund ever executed
    }
    assert len(calls(report, "refund_payment")) == 3
    assert calls(report, "restore_inventory") == []
    assert report.faulted.classification is OutcomeClassification.DETECTED_FAILURE


def test_naive_agent_reports_success_over_partial_state() -> None:
    report = run("naive", "refund-timeout-before-call")
    assert report.faulted.outcome is RunOutcome.FAIL
    assert report.faulted.agent.final_message is not None
    assert "refunded" in report.faulted.agent.final_message
    assert report.faulted.classification is OutcomeClassification.SILENT_FAILURE


def test_idempotency_key_makes_retry_after_commit_safe() -> None:
    report = run("idempotent", "refund-timeout-after-commit")
    refunds = calls(report, "refund_payment")

    assert len(refunds) == 2  # the agent did retry...
    assert all(i.underlying_operation_executed for i in refunds)
    assert len(final_state(report)["refunds"]) == 1  # ...but only one refund exists.
    assert report.comparison.verdict is ComparisonVerdict.RESILIENT


def test_idempotency_keys_do_not_help_operations_without_key_support() -> None:
    report = run("idempotent", "inventory-timeout-after-commit")
    assert statuses(report)["inventory_restored"] is InvariantStatus.FAIL
    assert len(calls(report, "restore_inventory")) == 2


def test_reconciliation_handles_timeout_after_commit_without_keys() -> None:
    report = run("reconciling", "inventory-timeout-after-commit")

    assert len(calls(report, "restore_inventory")) == 1
    assert len(calls(report, "get_inventory")) == 2  # probe before, probe before retry
    assert statuses(report)["inventory_restored"] is InvariantStatus.PASS
    assert report.comparison.verdict is ComparisonVerdict.RESILIENT


@pytest.mark.parametrize(("agent", "refunds"), [("retrying", 2), ("idempotent", 1)])
def test_duplicate_request_is_prevented_only_by_server_side_idempotency(
    agent: str, refunds: int
) -> None:
    report = run(agent, "refund-duplicate-request")
    first = calls(report, "refund_payment")[0]

    assert first.underlying_execution_count == 2
    assert len(final_state(report)["refunds"]) == refunds


def test_malformed_response_after_commit_triggers_unsafe_retry_without_key() -> None:
    unsafe = run("retrying", "refund-malformed-response")
    safe = run("idempotent", "refund-malformed-response")
    assert len(final_state(unsafe)["refunds"]) == 2
    assert len(final_state(safe)["refunds"]) == 1


# The full agent x fault matrix, pinned so any semantic regression is visible in review.
EXPECTED_MATRIX = {
    "refund-timeout-after-commit": ("correct", "silent_failure", "correct", "correct"),
    "refund-timeout-before-call": ("silent_failure", "correct", "correct", "correct"),
    "refund-rate-limited": ("silent_failure", "correct", "correct", "correct"),
    "refund-outage": (
        "silent_failure",
        "detected_failure",
        "detected_failure",
        "detected_failure",
    ),
    "refund-malformed-response": ("correct", "silent_failure", "correct", "correct"),
    "refund-duplicate-request": ("silent_failure", "silent_failure", "correct", "correct"),
    "inventory-timeout-after-commit": ("correct", "silent_failure", "silent_failure", "correct"),
    "confirmation-timeout-after-commit": ("correct", "silent_failure", "correct", "correct"),
    "cancel-latency": ("correct", "correct", "correct", "correct"),
}


@pytest.mark.parametrize("fault_case", list(EXPECTED_MATRIX))
def test_agent_fault_matrix(fault_case: str) -> None:
    agents = ("naive", "retrying", "idempotent", "reconciling")
    observed = tuple(run(agent, fault_case).faulted.classification.value for agent in agents)
    assert observed == EXPECTED_MATRIX[fault_case]


def test_every_baseline_is_a_valid_control() -> None:
    for agent in AGENT_PROFILES:
        assert run(agent, "none").baseline.outcome is RunOutcome.PASS
