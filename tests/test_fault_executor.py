import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue

from rift_core import ExecutionContext, FaultRule, FaultType, RunMode
from rift_fault_engine import (
    AmbiguousToolOutcomeError,
    DirectToolExecutor,
    FaultInjectingToolExecutor,
    InjectedRateLimitError,
    InjectedTimeoutError,
    InjectedToolException,
    ToolExecution,
)


class FakeClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 9, 18, tzinfo=UTC)
        self._monotonic = 100.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds


class FakeSleeper:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.clock.advance(seconds)


class DependencyFailure(RuntimeError):
    pass


def context(run_id: str = "run-1", run_mode: RunMode = RunMode.FAULTED) -> ExecutionContext:
    return ExecutionContext(
        experiment_id="experiment-1",
        run_id=run_id,
        seed=42,
        run_mode=run_mode,
    )


def rule(
    fault_type: FaultType,
    *,
    tool_name: str = "tool",
    invocation_number: int = 1,
    **configuration: object,
) -> FaultRule:
    return FaultRule.model_validate(
        {
            "fault_rule_id": f"{tool_name}-{invocation_number}-{fault_type.value}",
            "tool_name": tool_name,
            "invocation_number": invocation_number,
            "fault_type": fault_type,
            **configuration,
        }
    )


def execute(
    executor: DirectToolExecutor | FaultInjectingToolExecutor,
    operation: Callable[[], Awaitable[JsonValue]],
    *,
    tool_name: str = "tool",
    arguments: dict[str, JsonValue] | None = None,
    execution_context: ExecutionContext | None = None,
) -> ToolExecution:
    return asyncio.run(
        executor.execute(
            tool_name=tool_name,
            arguments=arguments or {},
            operation=operation,
            execution_context=execution_context or context(),
        )
    )


def test_direct_executor_executes_and_records_normally() -> None:
    calls = 0

    async def operation() -> JsonValue:
        nonlocal calls
        calls += 1
        return {"status": "ok"}

    executor = DirectToolExecutor(clock=FakeClock())
    outcome = execute(executor, operation, arguments={"resource_id": "R-1"})

    assert calls == 1
    assert outcome.result == {"status": "ok"}
    assert outcome.invocation == executor.invocations[0]
    assert outcome.invocation.invocation_number == 1
    assert outcome.invocation.arguments == {"resource_id": "R-1"}
    assert outcome.invocation.underlying_operation_executed is True
    assert outcome.invocation.underlying_operation_committed is None
    assert outcome.invocation.underlying_result == {"status": "ok"}
    assert outcome.invocation.caller_response == {"status": "ok"}
    assert outcome.invocation.fault_type is None


def test_baseline_run_ignores_configured_fault_rules() -> None:
    async def operation() -> JsonValue:
        return {"status": "ok"}

    executor = FaultInjectingToolExecutor(
        [rule(FaultType.EXCEPTION, error_message="should not happen")],
        clock=FakeClock(),
    )
    outcome = execute(
        executor,
        operation,
        execution_context=context(run_mode=RunMode.BASELINE),
    )

    assert outcome.result == {"status": "ok"}
    assert outcome.invocation.fault_type is None


def test_latency_uses_fake_sleeper_and_executes_once() -> None:
    calls = 0
    clock = FakeClock()
    sleeper = FakeSleeper(clock)

    async def operation() -> JsonValue:
        nonlocal calls
        calls += 1
        return "done"

    executor = FaultInjectingToolExecutor(
        [rule(FaultType.LATENCY, delay_ms=250)],
        clock=clock,
        sleeper=sleeper,
    )
    outcome = execute(executor, operation)

    assert sleeper.calls == [0.25]
    assert calls == 1
    assert outcome.result == "done"
    assert outcome.invocation.fault_type is FaultType.LATENCY
    assert outcome.invocation.duration_ms == pytest.approx(250.0)


def test_injected_exception_prevents_operation_execution() -> None:
    calls = 0

    async def operation() -> JsonValue:
        nonlocal calls
        calls += 1
        return "not reached"

    executor = FaultInjectingToolExecutor(
        [rule(FaultType.EXCEPTION, error_message="dependency failed")],
        clock=FakeClock(),
    )

    with pytest.raises(InjectedToolException, match="dependency failed") as raised:
        execute(executor, operation)

    assert calls == 0
    assert raised.value.invocation == executor.invocations[0]
    assert raised.value.invocation.underlying_operation_executed is False
    assert raised.value.invocation.underlying_operation_committed is False


def test_rate_limit_prevents_execution_and_exposes_retry_metadata() -> None:
    calls = 0

    async def operation() -> JsonValue:
        nonlocal calls
        calls += 1
        return "not reached"

    executor = FaultInjectingToolExecutor(
        [rule(FaultType.RATE_LIMIT, error_message="try later")],
        clock=FakeClock(),
    )

    with pytest.raises(InjectedRateLimitError) as raised:
        execute(executor, operation)

    assert calls == 0
    assert raised.value.status_code == 429
    assert raised.value.retryable is True
    assert raised.value.retry_after_seconds is None
    assert raised.value.invocation.underlying_operation_executed is False


def test_timeout_before_call_leaves_state_unchanged() -> None:
    state = {"updates": 0}

    async def operation() -> JsonValue:
        state["updates"] += 1
        return {"updates": state["updates"]}

    executor = FaultInjectingToolExecutor(
        [rule(FaultType.TIMEOUT_BEFORE_CALL, error_message="timed out")],
        clock=FakeClock(),
    )

    with pytest.raises(InjectedTimeoutError) as raised:
        execute(executor, operation)

    invocation = raised.value.invocation
    assert state == {"updates": 0}
    assert raised.value.operation_definitely_not_executed is True
    assert raised.value.operation_may_have_completed is False
    assert invocation.underlying_operation_executed is False
    assert invocation.underlying_operation_committed is False


def test_timeout_after_commit_mutates_state_and_raises_ambiguous_error() -> None:
    state = {"updates": 0}

    async def operation() -> JsonValue:
        state["updates"] += 1
        return {"status": "success"}

    executor = FaultInjectingToolExecutor(
        [rule(FaultType.TIMEOUT_AFTER_COMMIT, error_message="response lost")],
        clock=FakeClock(),
    )

    with pytest.raises(AmbiguousToolOutcomeError, match="response lost") as raised:
        execute(executor, operation)

    invocation = raised.value.invocation
    assert state == {"updates": 1}
    assert raised.value.operation_may_have_completed is True
    assert raised.value.operation_definitely_not_executed is False
    assert invocation.underlying_operation_executed is True
    assert invocation.underlying_operation_committed is True
    assert invocation.underlying_result == {"status": "success"}
    assert invocation.caller_response is None
    assert invocation.caller_error == "response lost"


def test_malformed_response_retains_actual_result_and_replaces_visible_result() -> None:
    calls = 0

    async def operation() -> JsonValue:
        nonlocal calls
        calls += 1
        return {"status": "success", "id": "R-1"}

    replacement = {"unexpected": "shape"}
    executor = FaultInjectingToolExecutor(
        [rule(FaultType.MALFORMED_RESPONSE, replacement_response=replacement)],
        clock=FakeClock(),
    )
    outcome = execute(executor, operation)

    assert calls == 1
    assert outcome.result == replacement
    assert outcome.invocation.underlying_result == {"status": "success", "id": "R-1"}
    assert outcome.invocation.caller_response == replacement
    assert outcome.invocation.fault_type is FaultType.MALFORMED_RESPONSE


def test_invocation_numbers_are_one_based_and_per_tool() -> None:
    async def operation() -> JsonValue:
        return "ok"

    executor = DirectToolExecutor(clock=FakeClock())
    outcomes = [
        execute(executor, operation, tool_name=tool_name)
        for tool_name in ("get_order", "refund_payment", "refund_payment", "get_order")
    ]

    assert [outcome.invocation.invocation_number for outcome in outcomes] == [1, 1, 2, 2]


def test_only_the_targeted_occurrence_receives_the_fault() -> None:
    calls = 0

    async def operation() -> JsonValue:
        nonlocal calls
        calls += 1
        return calls

    executor = FaultInjectingToolExecutor(
        [
            rule(
                FaultType.EXCEPTION,
                tool_name="refund_payment",
                invocation_number=2,
                error_message="targeted failure",
            )
        ],
        clock=FakeClock(),
    )

    first = execute(executor, operation, tool_name="refund_payment")
    with pytest.raises(InjectedToolException):
        execute(executor, operation, tool_name="refund_payment")
    third = execute(executor, operation, tool_name="refund_payment")

    assert first.result == 1
    assert third.result == 2
    assert calls == 2
    assert [item.fault_type for item in executor.invocations] == [
        None,
        FaultType.EXCEPTION,
        None,
    ]


def test_underlying_exception_is_recorded_and_propagated_without_injected_label() -> None:
    async def operation() -> JsonValue:
        raise DependencyFailure("service unavailable")

    executor = FaultInjectingToolExecutor(
        [rule(FaultType.TIMEOUT_AFTER_COMMIT)],
        clock=FakeClock(),
    )

    with pytest.raises(DependencyFailure, match="service unavailable"):
        execute(executor, operation)

    invocation = executor.invocations[0]
    assert invocation.underlying_operation_executed is True
    assert invocation.underlying_operation_committed is None
    assert invocation.underlying_error == "DependencyFailure: service unavailable"
    assert invocation.caller_error == "DependencyFailure: service unavailable"
    assert invocation.fault_rule_id is None
    assert invocation.fault_type is None
    assert invocation.fault_phase is None


def test_executor_rejects_multiple_rules_for_one_invocation() -> None:
    with pytest.raises(ValueError, match="only one fault rule"):
        FaultInjectingToolExecutor(
            [
                rule(FaultType.EXCEPTION),
                rule(FaultType.RATE_LIMIT),
            ]
        )


def test_invocation_state_does_not_leak_between_runs() -> None:
    async def operation() -> JsonValue:
        return "not reached"

    executor = FaultInjectingToolExecutor(
        [rule(FaultType.EXCEPTION)],
        clock=FakeClock(),
    )

    with pytest.raises(InjectedToolException):
        execute(executor, operation, execution_context=context("run-1"))
    with pytest.raises(InjectedToolException):
        execute(executor, operation, execution_context=context("run-2"))

    assert [item.invocation_number for item in executor.invocations] == [1, 1]
    assert len(executor.invocations_for(context("run-1"))) == 1
    assert len(executor.invocations_for(context("run-2"))) == 1


def test_ambiguous_timeout_retry_demonstrates_duplicate_side_effects() -> None:
    state = {"charges": 0}

    async def create_charge() -> JsonValue:
        state["charges"] += 1
        return {"status": "success"}

    executor = FaultInjectingToolExecutor(
        [
            rule(
                FaultType.TIMEOUT_AFTER_COMMIT,
                tool_name="create_charge",
                error_message="charge response timed out",
            )
        ],
        clock=FakeClock(),
    )

    with pytest.raises(AmbiguousToolOutcomeError):
        execute(executor, create_charge, tool_name="create_charge")

    assert state["charges"] == 1

    retry = execute(executor, create_charge, tool_name="create_charge")

    assert retry.result == {"status": "success"}
    assert state["charges"] == 2
    assert executor.invocations[0].underlying_operation_committed is True
    assert executor.invocations[1].fault_type is None
