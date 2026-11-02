"""Bind scenario tools to the fault-injecting executor and normalize what agents observe."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import JsonValue

from rift_core import (
    ExecutionContext,
    ToolCallOutcome,
    ToolErrorKind,
    ToolHandler,
    ToolSpec,
)
from rift_fault_engine import (
    InjectedRateLimitError,
    InjectedTimeoutError,
    InjectedToolException,
    ToolExecutor,
)


class ExecutorToolGateway:
    """The agent-facing tool boundary for one run.

    Every call goes through ``executor`` so it is numbered, possibly faulted, and recorded.
    Errors are converted into :class:`ToolCallOutcome` values. Both injected timeout kinds map to
    an identical outcome: a real caller cannot distinguish a timeout before execution from one
    after commit, and exposing that difference would hand the agent an oracle.
    """

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        handlers: Mapping[str, ToolHandler],
        specs: tuple[ToolSpec, ...],
        execution_context: ExecutionContext,
        max_tool_calls: int,
    ) -> None:
        self._executor = executor
        self._handlers = dict(handlers)
        self._specs = specs
        self._context = execution_context
        self._max_tool_calls = max_tool_calls
        self._calls = 0

    @property
    def tools(self) -> tuple[ToolSpec, ...]:
        return self._specs

    @property
    def calls_made(self) -> int:
        return self._calls

    async def call(self, tool_name: str, arguments: dict[str, JsonValue]) -> ToolCallOutcome:
        if self._calls >= self._max_tool_calls:
            return _failure(
                tool_name,
                ToolErrorKind.CALL_BUDGET_EXHAUSTED,
                f"Tool-call budget of {self._max_tool_calls} exhausted.",
            )
        self._calls += 1

        handler = self._handlers.get(tool_name)
        if handler is None:
            return _failure(tool_name, ToolErrorKind.UNKNOWN_TOOL, f"Unknown tool: {tool_name}.")

        async def operation() -> JsonValue:
            return await handler(arguments)

        try:
            execution = await self._executor.execute(
                tool_name=tool_name,
                arguments=arguments,
                operation=operation,
                execution_context=self._context,
            )
        except InjectedTimeoutError:  # Includes AmbiguousToolOutcomeError, intentionally.
            return _failure(
                tool_name,
                ToolErrorKind.TIMEOUT,
                f"Timed out waiting for a response from {tool_name}.",
                retryable=True,
            )
        except InjectedRateLimitError as error:
            return _failure(tool_name, ToolErrorKind.RATE_LIMITED, str(error), retryable=True)
        except InjectedToolException as error:
            # Present injected exceptions like an ordinary dependency failure, not as RIFT's.
            return _failure(tool_name, ToolErrorKind.TOOL_ERROR, f"DependencyError: {error}")
        except Exception as error:
            message = str(error).strip()
            text = f"{type(error).__name__}: {message}" if message else type(error).__name__
            return _failure(tool_name, ToolErrorKind.TOOL_ERROR, text)

        return ToolCallOutcome(tool_name=tool_name, ok=True, response=execution.result)


def _failure(
    tool_name: str, kind: ToolErrorKind, message: str, *, retryable: bool = False
) -> ToolCallOutcome:
    return ToolCallOutcome(
        tool_name=tool_name,
        ok=False,
        error_kind=kind,
        error_message=message,
        retryable=retryable,
    )
