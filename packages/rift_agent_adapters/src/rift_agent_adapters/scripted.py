"""A deterministic agent that follows a fixed script of tool calls with explicit recovery rules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import JsonValue

from rift_core import (
    AgentRunOutput,
    AgentStatus,
    AgentTask,
    ToolCallOutcome,
    ToolErrorKind,
    ToolGateway,
)

DEFAULT_RETRY_ON = frozenset({ToolErrorKind.TIMEOUT, ToolErrorKind.RATE_LIMITED})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """When a step may be attempted again. ``max_attempts=1`` means never retry."""

    max_attempts: int = 1
    retry_on: frozenset[ToolErrorKind] = DEFAULT_RETRY_ON
    retry_on_invalid_response: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Read state before a retry to decide whether a prior ambiguous attempt already applied.

    ``probe_tool`` is called once before the first attempt and again before every retry.
    ``already_applied(before, now)`` compares the two probe responses.
    """

    probe_tool: str
    probe_arguments: dict[str, JsonValue]
    already_applied: Callable[[JsonValue, JsonValue], bool]


@dataclass(frozen=True, slots=True)
class ScriptStep:
    """One intended action and the agent's recovery behavior for it."""

    tool_name: str
    arguments: dict[str, JsonValue] = field(default_factory=dict)
    retry: RetryPolicy = RetryPolicy()
    validate_response: Callable[[JsonValue], bool] | None = None
    reconcile: Reconciliation | None = None


@dataclass(slots=True)
class _StepOutcome:
    succeeded: bool
    reason: str


class ScriptedAgentAdapter:
    """Execute a script through the public tool gateway; no fault or evaluation logic here.

    ``on_step_failure`` decides whether the agent stops (``abort``) or moves on (``continue``).
    ``honest_reporting=False`` models an overconfident agent that always claims success, which
    is exactly the behavior outcome-based evaluation exists to catch.
    """

    def __init__(
        self,
        *,
        name: str,
        steps: Sequence[ScriptStep],
        version: str = "1",
        on_step_failure: Literal["abort", "continue"] = "abort",
        honest_reporting: bool = True,
        success_message: str = "Task completed.",
        failure_message: str = "Task could not be completed.",
    ) -> None:
        if not steps:
            raise ValueError("a script requires at least one step")
        self._name = name
        self._version = version
        self._steps = tuple(steps)
        self._on_step_failure = on_step_failure
        self._honest_reporting = honest_reporting
        self._success_message = success_message
        self._failure_message = failure_message

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    async def run(self, task: AgentTask, gateway: ToolGateway) -> AgentRunOutput:
        transcript: list[JsonValue] = []
        failed_steps: list[str] = []
        calls = 0

        async def call(tool_name: str, arguments: dict[str, JsonValue]) -> ToolCallOutcome:
            nonlocal calls
            calls += 1
            return await gateway.call(tool_name, arguments)

        for index, step in enumerate(self._steps, start=1):
            outcome = await self._run_step(index, step, call, transcript)
            if not outcome.succeeded:
                failed_steps.append(f"{index}:{step.tool_name} ({outcome.reason})")
                if self._on_step_failure == "abort":
                    break

        claims_success = not failed_steps or not self._honest_reporting
        if claims_success:
            status, message = AgentStatus.COMPLETED, self._success_message
        else:
            status = AgentStatus.GAVE_UP
            message = f"{self._failure_message} Failed steps: {', '.join(failed_steps)}."
        return AgentRunOutput(
            status=status,
            final_message=message,
            tool_calls=calls,
            metadata={"transcript": transcript, "failed_steps": list(failed_steps)},
        )

    async def _run_step(
        self,
        index: int,
        step: ScriptStep,
        call: Callable[[str, dict[str, JsonValue]], Awaitable[ToolCallOutcome]],
        transcript: list[JsonValue],
    ) -> _StepOutcome:
        probe_before: JsonValue = None
        if step.reconcile is not None:
            probe = await call(step.reconcile.probe_tool, step.reconcile.probe_arguments)
            transcript.append(_entry(index, "probe", step.reconcile.probe_tool, probe))
            probe_before = probe.response if probe.ok else None

        reason = "not attempted"
        for attempt in range(1, step.retry.max_attempts + 1):
            if attempt > 1 and step.reconcile is not None and probe_before is not None:
                probe = await call(step.reconcile.probe_tool, step.reconcile.probe_arguments)
                transcript.append(_entry(index, "probe", step.reconcile.probe_tool, probe))
                if probe.ok and step.reconcile.already_applied(probe_before, probe.response):
                    transcript.append(
                        {"step": index, "action": "reconciled", "tool": step.tool_name}
                    )
                    return _StepOutcome(True, "reconciled")

            outcome = await call(step.tool_name, step.arguments)
            transcript.append(_entry(index, f"attempt {attempt}", step.tool_name, outcome))

            if outcome.ok:
                if step.validate_response is None or step.validate_response(outcome.response):
                    return _StepOutcome(True, "ok")
                reason = "invalid response"
                if not step.retry.retry_on_invalid_response:
                    return _StepOutcome(False, reason)
                continue

            assert outcome.error_kind is not None
            reason = outcome.error_kind.value
            if outcome.error_kind not in step.retry.retry_on:
                return _StepOutcome(False, reason)

        return _StepOutcome(False, f"{reason}, retries exhausted")


def _entry(index: int, action: str, tool_name: str, outcome: ToolCallOutcome) -> JsonValue:
    return {
        "step": index,
        "action": action,
        "tool": tool_name,
        "ok": outcome.ok,
        "error_kind": outcome.error_kind.value if outcome.error_kind else None,
    }
