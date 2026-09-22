"""Framework-neutral domain models for RIFT experiments and run evidence."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PositiveInt,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


class RunMode(StrEnum):
    """Whether a run is the control or has fault rules enabled."""

    BASELINE = "baseline"
    FAULTED = "faulted"


class FaultPhase(StrEnum):
    """The side of the underlying tool call on which a fault is observed."""

    BEFORE_CALL = "before_call"
    AFTER_CALL = "after_call"


class FaultType(StrEnum):
    """The deterministic fault behaviors supported by the domain model."""

    LATENCY = "latency"
    EXCEPTION = "exception"
    RATE_LIMIT = "rate_limit"
    TIMEOUT_BEFORE_CALL = "timeout_before_call"
    TIMEOUT_AFTER_COMMIT = "timeout_after_commit"
    MALFORMED_RESPONSE = "malformed_response"

    @property
    def phase(self) -> FaultPhase:
        """Return the only valid phase for this fault type in the current model."""

        if self in {FaultType.TIMEOUT_AFTER_COMMIT, FaultType.MALFORMED_RESPONSE}:
            return FaultPhase.AFTER_CALL
        return FaultPhase.BEFORE_CALL

    @property
    def underlying_operation_executes(self) -> bool:
        """Whether applying this fault permits the underlying operation to execute."""

        return self not in {
            FaultType.EXCEPTION,
            FaultType.RATE_LIMIT,
            FaultType.TIMEOUT_BEFORE_CALL,
        }

    @property
    def commits_before_caller_error(self) -> bool:
        """Whether the fault guarantees a commit before hiding success from the caller."""

        return self is FaultType.TIMEOUT_AFTER_COMMIT


class InvariantStatus(StrEnum):
    """Outcome of evaluating one invariant."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


class RunOutcome(StrEnum):
    """Aggregate outcome of one experiment run."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    INCONCLUSIVE = "inconclusive"


class RiftDomainModel(BaseModel):
    """Strict, immutable base configuration for core domain values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FaultRule(RiftDomainModel):
    """A deterministic fault applied to one occurrence of one tool call."""

    fault_rule_id: NonEmptyStr
    tool_name: NonEmptyStr
    invocation_number: PositiveInt
    fault_type: FaultType
    phase: FaultPhase | None = None
    delay_ms: int | None = Field(default=None, gt=0)
    error_message: NonEmptyStr | None = None
    replacement_response: JsonValue | None = None

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        expected_phase = self.fault_type.phase
        if self.phase is None:
            object.__setattr__(self, "phase", expected_phase)
        elif self.phase is not expected_phase:
            raise ValueError(f"{self.fault_type.value} must use the {expected_phase.value} phase")

        if self.fault_type is FaultType.LATENCY:
            if self.delay_ms is None:
                raise ValueError("latency faults require delay_ms")
        elif self.delay_ms is not None:
            raise ValueError("delay_ms is only valid for latency faults")

        if self.fault_type is FaultType.MALFORMED_RESPONSE:
            if self.replacement_response is None:
                raise ValueError("malformed-response faults require replacement_response")
        elif self.replacement_response is not None:
            raise ValueError("replacement_response is only valid for malformed-response faults")

        supports_error_message = {
            FaultType.EXCEPTION,
            FaultType.RATE_LIMIT,
            FaultType.TIMEOUT_BEFORE_CALL,
            FaultType.TIMEOUT_AFTER_COMMIT,
        }
        if self.error_message is not None and self.fault_type not in supports_error_message:
            raise ValueError(f"error_message is not valid for {self.fault_type.value} faults")

        return self

    @property
    def underlying_operation_executes(self) -> bool:
        """Expose execution semantics without performing the fault."""

        return self.fault_type.underlying_operation_executes

    @property
    def commits_before_caller_error(self) -> bool:
        """Expose commit ambiguity semantics without performing the fault."""

        return self.fault_type.commits_before_caller_error

    def matches(
        self,
        *,
        tool_name: str,
        invocation_number: int,
        run_mode: RunMode,
    ) -> bool:
        """Match one invocation deterministically; baseline runs never activate faults."""

        return (
            run_mode is RunMode.FAULTED
            and self.tool_name == tool_name
            and self.invocation_number == invocation_number
        )


class ScenarioSpec(RiftDomainModel):
    """A versioned task, initial state, and declared tool/invariant surface."""

    scenario_id: NonEmptyStr
    name: NonEmptyStr
    task: NonEmptyStr
    version: PositiveInt = 1
    initial_state: dict[str, JsonValue] = Field(default_factory=dict)
    tool_names: tuple[NonEmptyStr, ...] = ()
    invariant_ids: tuple[NonEmptyStr, ...] = ()

    @field_validator("tool_names", "invariant_ids")
    @classmethod
    def require_unique_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("values must be unique and ordered")
        return values


class ExperimentSpec(RiftDomainModel):
    """An immutable experiment definition, distinct from any execution attempt."""

    experiment_id: NonEmptyStr
    name: NonEmptyStr
    scenario: ScenarioSpec
    seed: NonNegativeInt
    fault_rules: tuple[FaultRule, ...] = ()
    description: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_fault_rules(self) -> Self:
        rule_ids = [rule.fault_rule_id for rule in self.fault_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("fault_rule_id values must be unique within an experiment")

        selectors = [(rule.tool_name, rule.invocation_number) for rule in self.fault_rules]
        if len(selectors) != len(set(selectors)):
            raise ValueError("only one fault rule may target a tool invocation")

        declared_tools = set(self.scenario.tool_names)
        unknown_tools = sorted(
            {rule.tool_name for rule in self.fault_rules if rule.tool_name not in declared_tools}
        )
        if unknown_tools:
            raise ValueError(f"fault rules reference undeclared tools: {unknown_tools}")

        return self


class ExecutionContext(RiftDomainModel):
    """Stable identifiers and deterministic inputs supplied to one run."""

    experiment_id: NonEmptyStr
    run_id: NonEmptyStr
    seed: NonNegativeInt
    run_mode: RunMode


class ToolInvocation(RiftDomainModel):
    """Caller-visible and underlying outcomes for one intercepted tool invocation."""

    invocation_id: NonEmptyStr
    run_id: NonEmptyStr
    tool_name: NonEmptyStr
    invocation_number: PositiveInt
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    started_at: AwareDatetime
    finished_at: AwareDatetime
    duration_ms: NonNegativeFloat
    fault_rule_id: NonEmptyStr | None = None
    fault_type: FaultType | None = None
    fault_phase: FaultPhase | None = None
    underlying_operation_executed: bool
    underlying_operation_committed: bool | None
    underlying_result: JsonValue | None = None
    underlying_error: NonEmptyStr | None = None
    caller_response: JsonValue | None = None
    caller_error: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_outcomes(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")

        if self.underlying_operation_committed and not self.underlying_operation_executed:
            raise ValueError("a committed operation must have executed")

        if not self.underlying_operation_executed:
            if self.underlying_operation_committed is not False:
                raise ValueError("a skipped operation has a known uncommitted outcome")
            if self.underlying_result is not None or self.underlying_error is not None:
                raise ValueError("a skipped operation cannot have an underlying outcome")

        if self.underlying_result is not None and self.underlying_error is not None:
            raise ValueError("an invocation cannot have both an underlying result and error")

        if self.caller_response is not None and self.caller_error is not None:
            raise ValueError("an invocation cannot expose both a response and an error")

        if self.fault_type is None:
            if self.fault_rule_id is not None or self.fault_phase is not None:
                raise ValueError("fault metadata requires fault_type")
            return self

        if self.fault_rule_id is None:
            raise ValueError("a faulted invocation requires fault_rule_id")

        expected_phase = self.fault_type.phase
        if self.fault_phase is None:
            object.__setattr__(self, "fault_phase", expected_phase)
        elif self.fault_phase is not expected_phase:
            raise ValueError(f"{self.fault_type.value} must use the {expected_phase.value} phase")

        if self.fault_type is FaultType.TIMEOUT_BEFORE_CALL:
            if (
                self.underlying_operation_executed
                or self.underlying_operation_committed is not False
            ):
                raise ValueError("timeout-before-call cannot execute or commit the operation")
            if self.caller_error is None:
                raise ValueError("timeout-before-call requires a caller-visible error")

        if self.fault_type is FaultType.TIMEOUT_AFTER_COMMIT:
            if not self.underlying_operation_executed or not self.underlying_operation_committed:
                raise ValueError("timeout-after-commit requires an executed, committed operation")
            if self.caller_error is None:
                raise ValueError("timeout-after-commit requires a caller-visible error")

        if self.underlying_operation_executed is not self.fault_type.underlying_operation_executes:
            raise ValueError(
                f"{self.fault_type.value} has contradictory underlying execution evidence"
            )

        return self


class StateSnapshot(RiftDomainModel):
    """An immutable observation of scenario-relevant external state."""

    snapshot_id: NonEmptyStr
    run_id: NonEmptyStr
    captured_at: AwareDatetime
    state: dict[str, JsonValue]
    schema_version: NonEmptyStr = "1"


class InvariantResult(RiftDomainModel):
    """The evidence-bearing result of evaluating one invariant."""

    invariant_id: NonEmptyStr
    status: InvariantStatus
    message: NonEmptyStr
    expected: JsonValue | None = None
    observed: JsonValue | None = None
    error: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_error(self) -> Self:
        if self.status is InvariantStatus.ERROR and self.error is None:
            raise ValueError("error status requires error details")
        if self.status is not InvariantStatus.ERROR and self.error is not None:
            raise ValueError("error details are only valid for error status")
        return self


class ExperimentRunResult(RiftDomainModel):
    """The terminal, framework-neutral evidence and assessment for one run."""

    context: ExecutionContext
    outcome: RunOutcome
    tool_invocations: tuple[ToolInvocation, ...] = ()
    state_snapshot: StateSnapshot | None = None
    invariant_results: tuple[InvariantResult, ...] = ()
    agent_response: str | None = None

    @model_validator(mode="after")
    def validate_run_references(self) -> Self:
        invocation_ids = [item.invocation_id for item in self.tool_invocations]
        if len(invocation_ids) != len(set(invocation_ids)):
            raise ValueError("tool invocation IDs must be unique within a run result")

        mismatched_invocations = [
            item.invocation_id
            for item in self.tool_invocations
            if item.run_id != self.context.run_id
        ]
        if mismatched_invocations:
            raise ValueError(f"tool invocations reference another run: {mismatched_invocations}")

        if self.state_snapshot is not None and self.state_snapshot.run_id != self.context.run_id:
            raise ValueError("state snapshot must reference the result's run")

        invariant_ids = [item.invariant_id for item in self.invariant_results]
        if len(invariant_ids) != len(set(invariant_ids)):
            raise ValueError("invariant IDs must be unique within a run result")

        return self
