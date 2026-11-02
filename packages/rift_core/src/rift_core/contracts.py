"""Framework-neutral contracts between the runner, agent adapters, and scenario tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol, Self

from pydantic import Field, JsonValue, PositiveInt, model_validator

from rift_core.domain import NonEmptyStr, RiftDomainModel

ToolHandler = Callable[[dict[str, JsonValue]], Awaitable[JsonValue]]
"""A scenario tool implementation: JSON-compatible arguments in, JSON-compatible result out."""


class ToolSpec(RiftDomainModel):
    """The description of one tool that an agent may call."""

    name: NonEmptyStr
    description: NonEmptyStr
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    """JSON Schema for the tool arguments, suitable for model-provider tool definitions."""


class ToolErrorKind(StrEnum):
    """Caller-visible failure categories.

    These are deliberately coarse. In particular there is one ``TIMEOUT`` kind: a caller cannot
    tell whether a timed-out operation executed, so RIFT must not tell the agent either.
    """

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    TOOL_ERROR = "tool_error"
    UNKNOWN_TOOL = "unknown_tool"
    CALL_BUDGET_EXHAUSTED = "call_budget_exhausted"


class ToolCallOutcome(RiftDomainModel):
    """What an agent observes after calling a tool. Never contains RIFT-internal evidence."""

    tool_name: NonEmptyStr
    ok: bool
    response: JsonValue | None = None
    error_kind: ToolErrorKind | None = None
    error_message: NonEmptyStr | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.ok and (self.error_kind is not None or self.error_message is not None):
            raise ValueError("a successful outcome cannot carry an error")
        if not self.ok and (self.error_kind is None or self.error_message is None):
            raise ValueError("a failed outcome requires error_kind and error_message")
        if not self.ok and self.response is not None:
            raise ValueError("a failed outcome cannot carry a response")
        return self


class ToolGateway(Protocol):
    """The only path through which an agent adapter may affect the scenario environment."""

    @property
    def tools(self) -> tuple[ToolSpec, ...]:
        """Return the tools available to the agent in declaration order."""

    async def call(self, tool_name: str, arguments: dict[str, JsonValue]) -> ToolCallOutcome:
        """Call a tool. Tool failures are returned as outcomes, never raised."""


class AgentTask(RiftDomainModel):
    """The task handed to an agent for one run."""

    scenario_id: NonEmptyStr
    instruction: NonEmptyStr
    max_tool_calls: PositiveInt = 50


class AgentStatus(StrEnum):
    """How an agent run ended, according to the agent itself."""

    COMPLETED = "completed"
    """The agent claims the task is done."""
    GAVE_UP = "gave_up"
    """The agent stopped and reports that it could not complete the task."""
    CRASHED = "crashed"
    """The adapter raised; the agent made no claim."""

    @property
    def claims_success(self) -> bool:
        return self is AgentStatus.COMPLETED


class AgentRunOutput(RiftDomainModel):
    """Normalized, provider-free result of running an agent. Diagnostic, never proof."""

    status: AgentStatus
    final_message: str | None = None
    tool_calls: int = Field(default=0, ge=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AgentAdapter(Protocol):
    """Runs one agent implementation against a task through a tool gateway.

    Adapters must not select faults, reset state, evaluate invariants, or persist results.
    """

    @property
    def name(self) -> str:
        """Return a stable adapter identifier."""

    @property
    def version(self) -> str:
        """Return the adapter or agent-definition version."""

    async def run(self, task: AgentTask, gateway: ToolGateway) -> AgentRunOutput:
        """Execute the task, calling tools only through ``gateway``."""
