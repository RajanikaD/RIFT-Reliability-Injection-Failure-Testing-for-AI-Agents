"""Deterministic execution boundaries for intercepted async tool calls."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import JsonValue

from rift_core import ExecutionContext, FaultRule, FaultType, ToolInvocation
from rift_fault_engine.exceptions import (
    AmbiguousToolOutcomeError,
    InjectedRateLimitError,
    InjectedTimeoutError,
    InjectedToolException,
)
from rift_fault_engine.timing import AsyncioSleeper, Clock, Sleeper, SystemClock

ToolOperation = Callable[[], Awaitable[JsonValue]]


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """A caller-visible value paired with its immutable invocation evidence."""

    result: JsonValue
    invocation: ToolInvocation


class InvocationRecorder(Protocol):
    """Sink used by executors to expose every completed invocation record."""

    @property
    def records(self) -> tuple[ToolInvocation, ...]:
        """Return records in completion order."""

    def record(self, invocation: ToolInvocation) -> None:
        """Store one finalized invocation record."""


class InMemoryInvocationRecorder:
    """Process-local recorder suitable for the deterministic local runner."""

    def __init__(self) -> None:
        self._records: list[ToolInvocation] = []

    @property
    def records(self) -> tuple[ToolInvocation, ...]:
        return tuple(self._records)

    def record(self, invocation: ToolInvocation) -> None:
        self._records.append(invocation)


class ToolExecutor(Protocol):
    """Framework-neutral async tool-execution contract."""

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: dict[str, JsonValue],
        operation: ToolOperation,
        execution_context: ExecutionContext,
    ) -> ToolExecution:
        """Execute an intercepted operation and return its visible result and evidence."""


class _BaseToolExecutor:
    def __init__(
        self,
        *,
        clock: Clock | None = None,
        recorder: InvocationRecorder | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._recorder = recorder or InMemoryInvocationRecorder()
        self._invocation_counts: dict[tuple[str, str, str], int] = {}

    @property
    def invocations(self) -> tuple[ToolInvocation, ...]:
        """Return all records emitted by this executor's recorder."""

        return self._recorder.records

    def invocations_for(self, execution_context: ExecutionContext) -> tuple[ToolInvocation, ...]:
        """Return records belonging to one run context."""

        return tuple(
            invocation
            for invocation in self.invocations
            if invocation.run_id == execution_context.run_id
        )

    def _next_invocation_number(
        self, *, tool_name: str, execution_context: ExecutionContext
    ) -> int:
        key = (
            execution_context.experiment_id,
            execution_context.run_id,
            tool_name,
        )
        invocation_number = self._invocation_counts.get(key, 0) + 1
        self._invocation_counts[key] = invocation_number
        return invocation_number

    def _record(
        self,
        *,
        tool_name: str,
        arguments: dict[str, JsonValue],
        invocation_number: int,
        execution_context: ExecutionContext,
        started_at: datetime,
        started_monotonic: float,
        fault_rule: FaultRule | None = None,
        underlying_operation_executed: bool,
        underlying_operation_committed: bool | None,
        underlying_result: JsonValue | None = None,
        underlying_error: str | None = None,
        caller_response: JsonValue | None = None,
        caller_error: str | None = None,
    ) -> ToolInvocation:
        finished_at = self._clock.now()
        duration_ms = (self._clock.monotonic() - started_monotonic) * 1000
        invocation = ToolInvocation.model_validate(
            {
                "invocation_id": (f"{execution_context.run_id}:{tool_name}:{invocation_number}"),
                "run_id": execution_context.run_id,
                "tool_name": tool_name,
                "invocation_number": invocation_number,
                "arguments": arguments,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "fault_rule_id": (fault_rule.fault_rule_id if fault_rule is not None else None),
                "fault_type": fault_rule.fault_type if fault_rule is not None else None,
                "fault_phase": fault_rule.phase if fault_rule is not None else None,
                "underlying_operation_executed": underlying_operation_executed,
                "underlying_operation_committed": underlying_operation_committed,
                "underlying_result": underlying_result,
                "underlying_error": underlying_error,
                "caller_response": caller_response,
                "caller_error": caller_error,
            }
        )
        self._recorder.record(invocation)
        return invocation

    async def _execute_direct_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, JsonValue],
        operation: ToolOperation,
        execution_context: ExecutionContext,
        invocation_number: int,
        fault_rule: FaultRule | None = None,
    ) -> ToolExecution:
        started_at = self._clock.now()
        started_monotonic = self._clock.monotonic()
        try:
            result = await operation()
        except Exception as error:
            error_text = _describe_error(error)
            self._record(
                tool_name=tool_name,
                arguments=arguments,
                invocation_number=invocation_number,
                execution_context=execution_context,
                started_at=started_at,
                started_monotonic=started_monotonic,
                fault_rule=fault_rule,
                underlying_operation_executed=True,
                underlying_operation_committed=None,
                underlying_error=error_text,
                caller_error=error_text,
            )
            raise

        invocation = self._record(
            tool_name=tool_name,
            arguments=arguments,
            invocation_number=invocation_number,
            execution_context=execution_context,
            started_at=started_at,
            started_monotonic=started_monotonic,
            fault_rule=fault_rule,
            underlying_operation_executed=True,
            underlying_operation_committed=None,
            underlying_result=result,
            caller_response=result,
        )
        return ToolExecution(result=result, invocation=invocation)


class DirectToolExecutor(_BaseToolExecutor):
    """Execute async operations without injecting configured faults."""

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: dict[str, JsonValue],
        operation: ToolOperation,
        execution_context: ExecutionContext,
    ) -> ToolExecution:
        invocation_number = self._next_invocation_number(
            tool_name=tool_name,
            execution_context=execution_context,
        )
        return await self._execute_direct_call(
            tool_name=tool_name,
            arguments=arguments,
            operation=operation,
            execution_context=execution_context,
            invocation_number=invocation_number,
        )


class FaultInjectingToolExecutor(_BaseToolExecutor):
    """Apply at most one deterministic fault rule around each tool call."""

    def __init__(
        self,
        fault_rules: Sequence[FaultRule],
        *,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        recorder: InvocationRecorder | None = None,
    ) -> None:
        super().__init__(clock=clock, recorder=recorder)
        self._fault_rules = tuple(fault_rules)
        self._sleeper = sleeper or AsyncioSleeper()
        selectors = [(rule.tool_name, rule.invocation_number) for rule in self._fault_rules]
        if len(selectors) != len(set(selectors)):
            raise ValueError("only one fault rule may target a tool invocation")

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: dict[str, JsonValue],
        operation: ToolOperation,
        execution_context: ExecutionContext,
    ) -> ToolExecution:
        invocation_number = self._next_invocation_number(
            tool_name=tool_name,
            execution_context=execution_context,
        )
        fault_rule = self._matching_rule(
            tool_name=tool_name,
            invocation_number=invocation_number,
            execution_context=execution_context,
        )

        if fault_rule is None:
            return await self._execute_direct_call(
                tool_name=tool_name,
                arguments=arguments,
                operation=operation,
                execution_context=execution_context,
                invocation_number=invocation_number,
            )

        if fault_rule.fault_type is FaultType.LATENCY:
            return await self._execute_latency(
                rule=fault_rule,
                tool_name=tool_name,
                arguments=arguments,
                operation=operation,
                execution_context=execution_context,
                invocation_number=invocation_number,
            )

        if fault_rule.fault_type in {
            FaultType.EXCEPTION,
            FaultType.RATE_LIMIT,
            FaultType.TIMEOUT_BEFORE_CALL,
        }:
            self._raise_before_call_fault(
                rule=fault_rule,
                tool_name=tool_name,
                arguments=arguments,
                execution_context=execution_context,
                invocation_number=invocation_number,
            )

        if fault_rule.fault_type is FaultType.TIMEOUT_AFTER_COMMIT:
            return await self._execute_timeout_after_commit(
                rule=fault_rule,
                tool_name=tool_name,
                arguments=arguments,
                operation=operation,
                execution_context=execution_context,
                invocation_number=invocation_number,
            )

        if fault_rule.fault_type is FaultType.MALFORMED_RESPONSE:
            return await self._execute_malformed_response(
                rule=fault_rule,
                tool_name=tool_name,
                arguments=arguments,
                operation=operation,
                execution_context=execution_context,
                invocation_number=invocation_number,
            )

        raise AssertionError(f"unsupported fault type: {fault_rule.fault_type}")

    def _matching_rule(
        self,
        *,
        tool_name: str,
        invocation_number: int,
        execution_context: ExecutionContext,
    ) -> FaultRule | None:
        return next(
            (
                rule
                for rule in self._fault_rules
                if rule.matches(
                    tool_name=tool_name,
                    invocation_number=invocation_number,
                    run_mode=execution_context.run_mode,
                )
            ),
            None,
        )

    async def _execute_latency(
        self,
        *,
        rule: FaultRule,
        tool_name: str,
        arguments: dict[str, JsonValue],
        operation: ToolOperation,
        execution_context: ExecutionContext,
        invocation_number: int,
    ) -> ToolExecution:
        if rule.delay_ms is None:  # Defensive; FaultRule validation already enforces this.
            raise AssertionError("latency rule is missing delay_ms")

        started_at = self._clock.now()
        started_monotonic = self._clock.monotonic()
        await self._sleeper.sleep(rule.delay_ms / 1000)
        try:
            result = await operation()
        except Exception as error:
            error_text = _describe_error(error)
            self._record(
                tool_name=tool_name,
                arguments=arguments,
                invocation_number=invocation_number,
                execution_context=execution_context,
                started_at=started_at,
                started_monotonic=started_monotonic,
                fault_rule=rule,
                underlying_operation_executed=True,
                underlying_operation_committed=None,
                underlying_error=error_text,
                caller_error=error_text,
            )
            raise

        invocation = self._record(
            tool_name=tool_name,
            arguments=arguments,
            invocation_number=invocation_number,
            execution_context=execution_context,
            started_at=started_at,
            started_monotonic=started_monotonic,
            fault_rule=rule,
            underlying_operation_executed=True,
            underlying_operation_committed=None,
            underlying_result=result,
            caller_response=result,
        )
        return ToolExecution(result=result, invocation=invocation)

    def _raise_before_call_fault(
        self,
        *,
        rule: FaultRule,
        tool_name: str,
        arguments: dict[str, JsonValue],
        execution_context: ExecutionContext,
        invocation_number: int,
    ) -> None:
        started_at = self._clock.now()
        started_monotonic = self._clock.monotonic()
        message = rule.error_message or _default_error_message(rule.fault_type)
        invocation = self._record(
            tool_name=tool_name,
            arguments=arguments,
            invocation_number=invocation_number,
            execution_context=execution_context,
            started_at=started_at,
            started_monotonic=started_monotonic,
            fault_rule=rule,
            underlying_operation_executed=False,
            underlying_operation_committed=False,
            caller_error=message,
        )

        if rule.fault_type is FaultType.EXCEPTION:
            raise InjectedToolException(message, invocation=invocation)
        if rule.fault_type is FaultType.RATE_LIMIT:
            raise InjectedRateLimitError(message, invocation=invocation)
        if rule.fault_type is FaultType.TIMEOUT_BEFORE_CALL:
            raise InjectedTimeoutError(message, invocation=invocation)
        raise AssertionError(f"not a before-call failure: {rule.fault_type}")

    async def _execute_timeout_after_commit(
        self,
        *,
        rule: FaultRule,
        tool_name: str,
        arguments: dict[str, JsonValue],
        operation: ToolOperation,
        execution_context: ExecutionContext,
        invocation_number: int,
    ) -> ToolExecution:
        started_at = self._clock.now()
        started_monotonic = self._clock.monotonic()
        try:
            result = await operation()
        except Exception as error:
            error_text = _describe_error(error)
            self._record(
                tool_name=tool_name,
                arguments=arguments,
                invocation_number=invocation_number,
                execution_context=execution_context,
                started_at=started_at,
                started_monotonic=started_monotonic,
                underlying_operation_executed=True,
                underlying_operation_committed=None,
                underlying_error=error_text,
                caller_error=error_text,
            )
            raise

        message = rule.error_message or _default_error_message(rule.fault_type)
        invocation = self._record(
            tool_name=tool_name,
            arguments=arguments,
            invocation_number=invocation_number,
            execution_context=execution_context,
            started_at=started_at,
            started_monotonic=started_monotonic,
            fault_rule=rule,
            underlying_operation_executed=True,
            underlying_operation_committed=True,
            underlying_result=result,
            caller_error=message,
        )
        raise AmbiguousToolOutcomeError(message, invocation=invocation)

    async def _execute_malformed_response(
        self,
        *,
        rule: FaultRule,
        tool_name: str,
        arguments: dict[str, JsonValue],
        operation: ToolOperation,
        execution_context: ExecutionContext,
        invocation_number: int,
    ) -> ToolExecution:
        started_at = self._clock.now()
        started_monotonic = self._clock.monotonic()
        try:
            underlying_result = await operation()
        except Exception as error:
            error_text = _describe_error(error)
            self._record(
                tool_name=tool_name,
                arguments=arguments,
                invocation_number=invocation_number,
                execution_context=execution_context,
                started_at=started_at,
                started_monotonic=started_monotonic,
                underlying_operation_executed=True,
                underlying_operation_committed=None,
                underlying_error=error_text,
                caller_error=error_text,
            )
            raise

        replacement_response = rule.replacement_response
        invocation = self._record(
            tool_name=tool_name,
            arguments=arguments,
            invocation_number=invocation_number,
            execution_context=execution_context,
            started_at=started_at,
            started_monotonic=started_monotonic,
            fault_rule=rule,
            underlying_operation_executed=True,
            underlying_operation_committed=None,
            underlying_result=underlying_result,
            caller_response=replacement_response,
        )
        return ToolExecution(result=replacement_response, invocation=invocation)


def _describe_error(error: Exception) -> str:
    message = str(error).strip()
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def _default_error_message(fault_type: FaultType) -> str:
    messages = {
        FaultType.EXCEPTION: "injected tool exception",
        FaultType.RATE_LIMIT: "injected rate limit",
        FaultType.TIMEOUT_BEFORE_CALL: "injected timeout before call",
        FaultType.TIMEOUT_AFTER_COMMIT: "injected timeout after commit",
    }
    return messages[fault_type]
