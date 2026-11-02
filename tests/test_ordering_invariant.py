"""D4 regression tests: business operations must happen in a valid order.

The defect (Milestone 1 closeout, M1-D4): every commerce invariant inspected only the final state.
A final state records *what* exists, not *when* it came to exist, so an agent that refunded an
order before cancelling it reached a state identical to a correct agent's and passed. Order is
only visible in the invocation trace, which the runner did not pass to invariants.

The ordering check uses the *underlying* execution evidence, not what the caller saw: a refund
that executed but whose response timed out still happened.
"""

from __future__ import annotations

import asyncio

from commerce_demo import CommerceSandbox
from commerce_demo.agents import reconciling_agent
from commerce_demo.ordering import RefundAfterCancellationInvariant
from commerce_demo.scenario import CommerceScenarioBinding, commerce_experiment
from rift_agent_adapters import RetryPolicy, ScriptedAgentAdapter, ScriptStep
from rift_core import FaultRule, FaultType, InvariantStatus, RunOutcome
from rift_experiment_runner import ExperimentReport, ExperimentRunner
from rift_invariant_engine import InvariantEvaluationContext, InvariantEvaluator

CANCEL = ScriptStep("cancel_order", {"order_id": "ORD-1001"})
REFUND = ScriptStep(
    "refund_payment",
    {"payment_id": "PAY-1001", "amount": "79.99", "idempotency_key": "refund-ORD-1001"},
)
RESTORE = ScriptStep("restore_inventory", {"sku": "SKU-HEADPHONES-001", "quantity": 1})
CONFIRM = ScriptStep("send_confirmation", {"order_id": "ORD-1001", "message": "Done."})


class NoSleep:
    async def sleep(self, seconds: float) -> None:
        return None


def agent(*steps: ScriptStep) -> ScriptedAgentAdapter:
    return ScriptedAgentAdapter(name="ordering-test", steps=steps, on_step_failure="continue")


def run(adapter, *rules: FaultRule) -> ExperimentReport:
    runner = ExperimentRunner(sleeper=NoSleep())
    experiment = commerce_experiment("ordering", rules)
    return asyncio.run(runner.run(experiment, CommerceScenarioBinding(), adapter))


def ordering_result(report: ExperimentReport, mode: str = "baseline"):
    run_report = report.baseline if mode == "baseline" else report.faulted
    return next(
        r
        for r in run_report.result.invariant_results
        if r.invariant_id == "refund_after_cancellation"
    )


def test_refunding_before_cancelling_fails_although_final_state_is_correct() -> None:
    report = run(agent(REFUND, CONFIRM, RESTORE, CANCEL))

    statuses = {r.invariant_id: r.status for r in report.baseline.result.invariant_results}
    state_only = {k: v for k, v in statuses.items() if k != "refund_after_cancellation"}
    assert set(state_only.values()) == {InvariantStatus.PASS}  # the end state looks perfect
    assert statuses["refund_after_cancellation"] is InvariantStatus.FAIL
    assert report.baseline.outcome is RunOutcome.FAIL


def test_correct_order_passes() -> None:
    report = run(reconciling_agent())
    assert ordering_result(report).status is InvariantStatus.PASS
    assert report.baseline.outcome is RunOutcome.PASS


def test_a_refund_that_never_executed_does_not_count_as_too_early() -> None:
    """Refund attempt 1 times out *before* executing, so only the later refund counts."""

    retry = RetryPolicy(max_attempts=1)
    early = ScriptStep(REFUND.tool_name, REFUND.arguments, retry=retry)
    report = run(
        agent(early, CANCEL, REFUND, RESTORE, CONFIRM),
        FaultRule(
            fault_rule_id="early-refund-timeout",
            tool_name="refund_payment",
            invocation_number=1,
            fault_type=FaultType.TIMEOUT_BEFORE_CALL,
        ),
    )
    assert ordering_result(report, "faulted").status is InvariantStatus.PASS
    assert report.faulted.outcome is RunOutcome.PASS


def test_a_refund_whose_response_was_lost_still_counts_as_too_early() -> None:
    """Attempt 1 commits but the caller sees a timeout. The agent believes no refund happened
    yet, but one did, before cancellation. The ordering check must use what actually ran."""

    report = run(
        agent(REFUND, CANCEL, REFUND, RESTORE, CONFIRM),
        FaultRule(
            fault_rule_id="early-refund-commit",
            tool_name="refund_payment",
            invocation_number=1,
            fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
        ),
    )
    assert len(report.faulted.result.state_snapshot.state["refunds"]) == 1  # key deduplicated
    assert ordering_result(report, "faulted").status is InvariantStatus.FAIL


def test_without_trace_evidence_the_ordering_invariant_errors_instead_of_passing() -> None:
    snapshot = CommerceSandbox().snapshot()
    context = InvariantEvaluationContext(before_state=snapshot, after_state=snapshot)
    summary = InvariantEvaluator([RefundAfterCancellationInvariant()]).evaluate(context)

    result = summary.results[0]
    assert result.status is InvariantStatus.ERROR
    assert result.error is not None and "trace evidence" in result.error
