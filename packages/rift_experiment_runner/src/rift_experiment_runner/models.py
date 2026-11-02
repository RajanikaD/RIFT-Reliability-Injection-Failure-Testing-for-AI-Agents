"""Serializable experiment reports produced by the runner."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from rift_core import (
    AgentRunOutput,
    ExperimentRunResult,
    ExperimentSpec,
    InvariantResult,
    InvariantStatus,
    RunMode,
    RunOutcome,
)


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OutcomeClassification(StrEnum):
    """What the agent claimed, crossed with what the state proves."""

    CORRECT = "correct"
    """State correct and the agent claimed success."""
    SILENT_FAILURE = "silent_failure"
    """State incorrect but the agent claimed success. The most dangerous outcome."""
    DETECTED_FAILURE = "detected_failure"
    """State incorrect and the agent reported that it could not finish."""
    UNCONFIRMED_SUCCESS = "unconfirmed_success"
    """State correct but the agent did not claim success (gave up or crashed)."""
    EVALUATION_ERROR = "evaluation_error"
    """Invariants could not be evaluated, so no claim about correctness is possible."""


class AdapterIdentity(ReportModel):
    name: str
    version: str


class RunReport(ReportModel):
    """One run: core result plus the agent's own account and the initial state."""

    mode: RunMode
    result: ExperimentRunResult
    agent: AgentRunOutput
    classification: OutcomeClassification
    initial_state: dict[str, JsonValue]
    fired_fault_rule_ids: tuple[str, ...] = ()
    fingerprint: str
    """SHA-256 over RIFT-controlled, timing-free evidence. Equal inputs give equal fingerprints."""

    @property
    def outcome(self) -> RunOutcome:
        return self.result.outcome


class ComparisonVerdict(StrEnum):
    RESILIENT = "resilient"
    """Baseline valid, faults fired, and the faulted run still satisfied every invariant."""
    DEGRADED = "degraded"
    """Baseline valid, faults fired, and the faulted run did not satisfy every invariant."""
    BASELINE_INVALID = "baseline_invalid"
    """The control run failed, so the comparison proves nothing about the faults."""
    NOT_EXERCISED = "not_exercised"
    """No configured fault was injected, so the experiment did not test what it intended."""


class InvariantDelta(ReportModel):
    invariant_id: str
    baseline: InvariantStatus | None
    faulted: InvariantStatus | None

    @property
    def changed(self) -> bool:
        return self.baseline is not self.faulted


class StateDifference(ReportModel):
    path: str
    change: Literal["added", "removed", "changed"]
    baseline: JsonValue = None
    faulted: JsonValue = None


class Comparison(ReportModel):
    verdict: ComparisonVerdict
    baseline_valid: bool
    explanation: str
    invariant_deltas: tuple[InvariantDelta, ...]
    state_differences: tuple[StateDifference, ...]
    unfired_fault_rule_ids: tuple[str, ...] = ()


class ExperimentReport(ReportModel):
    """Everything needed to understand and reproduce one baseline-versus-faulted experiment."""

    experiment: ExperimentSpec
    adapter: AdapterIdentity
    baseline: RunReport
    faulted: RunReport
    comparison: Comparison
    rift_version: str = Field(default="0.1.0")

    def failing_invariants(self) -> tuple[InvariantResult, ...]:
        return tuple(
            result
            for result in self.faulted.result.invariant_results
            if result.status is not InvariantStatus.PASS
        )
