"""D2 regression tests: invocations carry a run-global start order and happens-before evidence.

The defect (Milestone 1 closeout, M1-D2): invocation numbers are per tool, and the trace was
recorded in *completion* order. Nothing recorded the order in which calls *started* across tools,
so "did the cancellation finish before the refund was requested?" could not be answered for
overlapping calls, and the D4 ordering invariant had to approximate with completion order.

Each invocation now records:
- ``sequence_number``: 1-based, run-global, assigned when the call starts.
- ``completed_before_start``: how many invocations in the run had finished when it started.
A call A happened-before call B iff A's completion position <= B's ``completed_before_start``.
"""

from __future__ import annotations

import asyncio

from pydantic import JsonValue

from commerce_demo.scenario import CommerceScenarioBinding, commerce_experiment
from rift_core import (
    AgentRunOutput,
    AgentStatus,
    AgentTask,
    ExecutionContext,
    FaultRule,
    FaultType,
    InvariantStatus,
    RunMode,
    ToolGateway,
)
from rift_experiment_runner import ExperimentRunner
from rift_fault_engine import FaultInjectingToolExecutor, InMemoryInvocationRecorder

CONTEXT = ExecutionContext(
    experiment_id="seq", run_id="seq:faulted", seed=0, run_mode=RunMode.FAULTED
)


def execute(executor, tool_name: str, ticks: int = 0):
    async def operation() -> JsonValue:
        for _ in range(ticks):
            await asyncio.sleep(0)
        return tool_name

    return executor.execute(
        tool_name=tool_name, arguments={}, operation=operation, execution_context=CONTEXT
    )


def test_sequence_numbers_are_run_global_and_follow_start_order() -> None:
    recorder = InMemoryInvocationRecorder()
    executor = FaultInjectingToolExecutor([], recorder=recorder)

    async def scenario() -> None:
        for tool in ("a", "b", "a"):
            await execute(executor, tool)

    asyncio.run(scenario())
    assert [(i.tool_name, i.invocation_number, i.sequence_number) for i in recorder.records] == [
        ("a", 1, 1),
        ("b", 1, 2),
        ("a", 2, 3),
    ]
    assert [i.completed_before_start for i in recorder.records] == [0, 1, 2]


def test_overlapping_calls_record_start_order_and_happens_before_evidence() -> None:
    recorder = InMemoryInvocationRecorder()
    executor = FaultInjectingToolExecutor([], recorder=recorder)

    async def scenario() -> None:
        await asyncio.gather(execute(executor, "slow", ticks=5), execute(executor, "fast"))
        await execute(executor, "after")

    asyncio.run(scenario())
    by_tool = {i.tool_name: i for i in recorder.records}
    assert [i.tool_name for i in recorder.records] == ["fast", "slow", "after"]  # completion
    assert (by_tool["slow"].sequence_number, by_tool["fast"].sequence_number) == (1, 2)
    # Neither overlapping call saw the other complete; "after" saw both.
    assert by_tool["slow"].completed_before_start == by_tool["fast"].completed_before_start == 0
    assert by_tool["after"].completed_before_start == 2


def test_sequence_numbers_restart_per_run() -> None:
    recorder = InMemoryInvocationRecorder()
    executor = FaultInjectingToolExecutor([], recorder=recorder)
    other = CONTEXT.model_copy(update={"run_id": "seq:other"})

    async def scenario() -> None:
        await execute(executor, "a")
        await executor.execute(
            tool_name="a", arguments={}, operation=_constant, execution_context=other
        )

    asyncio.run(scenario())
    assert [i.sequence_number for i in recorder.records] == [1, 1]


async def _constant() -> JsonValue:
    return 1


class TickSleeper:
    """Latency in event-loop ticks instead of real time: delay_ms=N yields N times."""

    async def sleep(self, seconds: float) -> None:
        for _ in range(round(seconds * 1000)):
            await asyncio.sleep(0)


class ConcurrentAgent:
    """Fires cancel and refund at once instead of waiting for the cancellation to finish."""

    name = "concurrent"
    version = "test"

    async def run(self, task: AgentTask, gateway: ToolGateway) -> AgentRunOutput:
        await asyncio.gather(
            gateway.call("cancel_order", {"order_id": "ORD-1001"}),
            gateway.call(
                "refund_payment",
                {"payment_id": "PAY-1001", "amount": "79.99", "idempotency_key": "k"},
            ),
        )
        await gateway.call("restore_inventory", {"sku": "SKU-HEADPHONES-001", "quantity": 1})
        await gateway.call(
            "send_confirmation", {"order_id": "ORD-1001", "message": "Cancelled and refunded."}
        )
        return AgentRunOutput(status=AgentStatus.COMPLETED, final_message="Done.")


def test_refund_requested_while_cancellation_in_flight_violates_ordering() -> None:
    """In the faulted run cancel takes 1 tick and refund 3, so cancel *completes* first, but the
    refund was *requested* before the cancellation finished. Completion order alone says the
    order is fine; happens-before evidence says it is not."""

    latency = [
        FaultRule(
            fault_rule_id="slow-cancel",
            tool_name="cancel_order",
            invocation_number=1,
            fault_type=FaultType.LATENCY,
            delay_ms=1,
        ),
        FaultRule(
            fault_rule_id="slower-refund",
            tool_name="refund_payment",
            invocation_number=1,
            fault_type=FaultType.LATENCY,
            delay_ms=3,
        ),
    ]
    runner = ExperimentRunner(sleeper=TickSleeper())
    report = asyncio.run(
        runner.run(
            commerce_experiment("concurrent", latency), CommerceScenarioBinding(), ConcurrentAgent()
        )
    )

    faulted_trace = [i.tool_name for i in report.faulted.result.tool_invocations]
    assert faulted_trace[:2] == ["cancel_order", "refund_payment"]  # completion order looks fine
    ordering = {r.invariant_id: r.status for r in report.faulted.result.invariant_results}
    assert ordering["refund_after_cancellation"] is InvariantStatus.FAIL
    # Without latency the sandbox runs each call to completion, so the baseline is sequential.
    baseline = {r.invariant_id: r.status for r in report.baseline.result.invariant_results}
    assert baseline["refund_after_cancellation"] is InvariantStatus.PASS
