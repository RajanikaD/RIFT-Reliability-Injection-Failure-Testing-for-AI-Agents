"""Runner lifecycle guarantees, exercised against the commerce scenario."""

import asyncio

import pytest
from pydantic import JsonValue

from commerce_demo.agents import naive_agent, reconciling_agent, retrying_agent
from commerce_demo.fault_cases import FAULT_CASES
from commerce_demo.scenario import (
    COMMERCE_SCENARIO,
    CommerceScenarioBinding,
    commerce_experiment,
)
from rift_core import (
    AgentRunOutput,
    AgentStatus,
    AgentTask,
    FaultRule,
    FaultType,
    InvariantStatus,
    RunOutcome,
    ToolGateway,
)
from rift_experiment_runner import (
    ComparisonVerdict,
    ExperimentConfigurationError,
    ExperimentReport,
    ExperimentRunner,
    OutcomeClassification,
)


class NoSleep:
    async def sleep(self, seconds: float) -> None:
        return None


class CustomAgent:
    """An adapter defined inline to prove the runner only needs the public contract."""

    def __init__(self, calls, status=AgentStatus.COMPLETED, message="All done!", crash=False):
        self._calls: list[tuple[str, dict[str, JsonValue]]] = calls
        self._status = status
        self._message = message
        self._crash = crash

    name = "custom"
    version = "test"

    async def run(self, task: AgentTask, gateway: ToolGateway) -> AgentRunOutput:
        for tool_name, arguments in self._calls:
            await gateway.call(tool_name, arguments)
        if self._crash:
            raise RuntimeError("model provider exploded")
        return AgentRunOutput(status=self._status, final_message=self._message)


FULL_SCRIPT = [
    ("cancel_order", {"order_id": "ORD-1001"}),
    ("refund_payment", {"payment_id": "PAY-1001", "amount": "79.99"}),
    ("restore_inventory", {"sku": "SKU-HEADPHONES-001", "quantity": 1}),
    ("send_confirmation", {"order_id": "ORD-1001", "message": "Cancelled."}),
]


def run(experiment, adapter) -> ExperimentReport:
    runner = ExperimentRunner(sleeper=NoSleep())
    return asyncio.run(runner.run(experiment, CommerceScenarioBinding(), adapter))


def case(name: str):
    return commerce_experiment(f"test-{name}", FAULT_CASES[name].rules)


def test_baseline_and_faulted_start_from_the_declared_initial_state() -> None:
    report = run(case("refund-timeout-after-commit"), retrying_agent())
    assert report.baseline.initial_state == COMMERCE_SCENARIO.initial_state
    assert report.faulted.initial_state == COMMERCE_SCENARIO.initial_state


def test_baseline_never_receives_faults_and_runs_use_distinct_ids() -> None:
    report = run(case("refund-outage"), retrying_agent())
    assert report.baseline.fired_fault_rule_ids == ()
    assert all(i.fault_type is None for i in report.baseline.result.tool_invocations)
    assert report.baseline.result.context.run_id != report.faulted.result.context.run_id


def test_repeated_experiments_are_reproducible() -> None:
    first = run(case("inventory-timeout-after-commit"), reconciling_agent())
    second = run(case("inventory-timeout-after-commit"), reconciling_agent())
    assert first.baseline.fingerprint == second.baseline.fingerprint
    assert first.faulted.fingerprint == second.faulted.fingerprint
    assert first.comparison == second.comparison


def test_faulted_run_mutations_do_not_leak_into_the_next_experiment() -> None:
    clean = run(case("none"), retrying_agent())
    run(case("refund-timeout-after-commit"), retrying_agent())  # creates a duplicate refund
    again = run(case("none"), retrying_agent())
    assert clean.baseline.fingerprint == again.baseline.fingerprint


def test_outcome_does_not_depend_on_agent_text() -> None:
    honest = CustomAgent(FULL_SCRIPT[:1], status=AgentStatus.GAVE_UP, message="I failed.")
    liar = CustomAgent(FULL_SCRIPT[:1], message="Cancelled, refunded, restocked, notified!")

    honest_report = run(case("none"), honest)
    liar_report = run(case("none"), liar)

    assert honest_report.faulted.outcome is liar_report.faulted.outcome is RunOutcome.FAIL
    assert honest_report.faulted.classification is OutcomeClassification.DETECTED_FAILURE
    assert liar_report.faulted.classification is OutcomeClassification.SILENT_FAILURE


def test_crashing_adapter_is_recorded_and_state_is_still_evaluated() -> None:
    report = run(case("none"), CustomAgent(FULL_SCRIPT, crash=True))
    faulted = report.faulted
    assert faulted.agent.status is AgentStatus.CRASHED
    assert "model provider exploded" in str(faulted.agent.metadata["error"])
    # The work completed before the crash, so the state is correct.
    assert faulted.outcome is RunOutcome.PASS
    assert faulted.classification is OutcomeClassification.UNCONFIRMED_SUCCESS


def test_invalid_baseline_invalidates_the_comparison() -> None:
    report = run(case("refund-timeout-after-commit"), CustomAgent(FULL_SCRIPT[:3]))
    assert report.baseline.outcome is RunOutcome.FAIL
    assert report.comparison.verdict is ComparisonVerdict.BASELINE_INVALID
    assert report.comparison.baseline_valid is False


def test_fault_that_never_fires_is_reported_as_not_exercised() -> None:
    second_refund = FaultRule(
        fault_rule_id="second-refund",
        tool_name="refund_payment",
        invocation_number=2,
        fault_type=FaultType.EXCEPTION,
    )
    report = run(commerce_experiment("unfired", [second_refund]), reconciling_agent())
    assert report.faulted.outcome is RunOutcome.PASS
    assert report.comparison.verdict is ComparisonVerdict.NOT_EXERCISED
    assert report.comparison.unfired_fault_rule_ids == ("second-refund",)


def test_partially_fired_rules_are_listed_without_hiding_the_verdict() -> None:
    rules = [
        FaultRule(
            fault_rule_id=f"refund-{number}",
            tool_name="refund_payment",
            invocation_number=number,
            fault_type=FaultType.TIMEOUT_BEFORE_CALL,
        )
        for number in (1, 5)
    ]
    report = run(commerce_experiment("partial", rules), reconciling_agent())
    assert report.comparison.verdict is ComparisonVerdict.RESILIENT
    assert report.comparison.unfired_fault_rule_ids == ("refund-5",)


def test_mismatched_scenario_version_is_rejected() -> None:
    experiment = case("none").model_copy(
        update={"scenario": COMMERCE_SCENARIO.model_copy(update={"version": 99})}
    )
    with pytest.raises(ExperimentConfigurationError, match="v99"):
        run(experiment, naive_agent())


def test_declared_invariants_must_match_evaluated_invariants() -> None:
    scenario = COMMERCE_SCENARIO.model_copy(update={"invariant_ids": ("order_cancelled",)})
    experiment = case("none").model_copy(update={"scenario": scenario})
    with pytest.raises(ExperimentConfigurationError, match="declared invariants"):
        run(experiment, naive_agent())


def test_report_round_trips_through_json() -> None:
    report = run(case("refund-duplicate-request"), retrying_agent())
    restored = ExperimentReport.model_validate_json(report.model_dump_json())
    assert restored == report
    assert [r.status for r in restored.faulted.result.invariant_results].count(
        InvariantStatus.FAIL
    ) == 2
