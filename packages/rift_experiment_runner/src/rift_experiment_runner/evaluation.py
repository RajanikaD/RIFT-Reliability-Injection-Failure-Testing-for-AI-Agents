"""Pure functions that turn run evidence into outcomes, classifications and comparisons.

These are kept separate from the runner so the rules that decide correctness are small,
side-effect free, and directly unit-testable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence

from pydantic import JsonValue

from rift_core import (
    AgentRunOutput,
    FaultRule,
    InvariantResult,
    InvariantStatus,
    RunOutcome,
    ToolInvocation,
    derive_run_outcome,
)
from rift_experiment_runner.models import (
    Comparison,
    ComparisonVerdict,
    InvariantDelta,
    OutcomeClassification,
    RunReport,
    StateDifference,
)


def derive_outcome(results: Sequence[InvariantResult]) -> RunOutcome:
    """Kept for compatibility; the rule itself lives in ``rift_core.derive_run_outcome``."""

    return derive_run_outcome(results)


def classify(outcome: RunOutcome, agent: AgentRunOutput) -> OutcomeClassification:
    if outcome is RunOutcome.PASS:
        if agent.status.claims_success:
            return OutcomeClassification.CORRECT
        return OutcomeClassification.UNCONFIRMED_SUCCESS
    if outcome is RunOutcome.FAIL:
        if agent.status.claims_success:
            return OutcomeClassification.SILENT_FAILURE
        return OutcomeClassification.DETECTED_FAILURE
    return OutcomeClassification.EVALUATION_ERROR


def fired_rule_ids(invocations: Iterable[ToolInvocation]) -> tuple[str, ...]:
    return tuple(item.fault_rule_id for item in invocations if item.fault_rule_id is not None)


def invocation_evidence(invocations: Sequence[ToolInvocation]) -> dict[str, JsonValue]:
    """Build the trace evidence that invariants may opt in to via their evaluation context.

    It describes what actually executed, never what the caller saw: an operation whose response
    was lost still ``succeeded``. ``completion_position`` is the 1-based order in which
    invocations finished; ``sequence_number`` the order in which they started; and A
    happened-before B iff A's ``completion_position`` <= B's ``completed_before_start``.
    """

    return {
        "invocations": [
            {
                "completion_position": position,
                "sequence_number": item.sequence_number,
                "completed_before_start": item.completed_before_start,
                "tool": item.tool_name,
                "invocation_number": item.invocation_number,
                "executed": item.underlying_operation_executed,
                "succeeded": item.underlying_operation_executed and item.underlying_error is None,
                "committed": item.underlying_operation_committed,
                "execution_count": item.underlying_execution_count,
                "fault_type": item.fault_type.value if item.fault_type else None,
            }
            for position, item in enumerate(invocations, start=1)
        ]
    }


def fingerprint(
    *,
    invocations: Sequence[ToolInvocation],
    final_state: dict[str, JsonValue],
    results: Sequence[InvariantResult],
    agent: AgentRunOutput,
) -> str:
    """Hash RIFT-controlled evidence, excluding wall-clock timing and generated prose."""

    payload = {
        "invocations": [
            {
                "tool": item.tool_name,
                "number": item.invocation_number,
                "sequence": item.sequence_number,
                "completed_before_start": item.completed_before_start,
                "arguments": item.arguments,
                "fault_rule_id": item.fault_rule_id,
                "executed": item.underlying_operation_executed,
                "committed": item.underlying_operation_committed,
                "execution_count": item.underlying_execution_count,
                "caller_failed": item.caller_error is not None,
            }
            for item in invocations
        ],
        "final_state": final_state,
        "invariants": {result.invariant_id: result.status.value for result in results},
        "agent_status": agent.status.value,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compare(
    baseline: RunReport, faulted: RunReport, fault_rules: Sequence[FaultRule]
) -> Comparison:
    baseline_valid = baseline.outcome is RunOutcome.PASS
    fired = set(faulted.fired_fault_rule_ids)
    unfired = tuple(rule.fault_rule_id for rule in fault_rules if rule.fault_rule_id not in fired)

    deltas = _invariant_deltas(baseline.result.invariant_results, faulted.result.invariant_results)
    differences = diff_states(
        _final_state(baseline),
        _final_state(faulted),
    )

    if not baseline_valid:
        verdict = ComparisonVerdict.BASELINE_INVALID
        explanation = (
            f"The fault-free baseline ended {baseline.outcome.value}, so it is not a valid "
            "control. Fix the agent or scenario before interpreting the faulted run."
        )
    elif not fired:
        verdict = ComparisonVerdict.NOT_EXERCISED
        explanation = (
            "No fault rule matched an invocation the agent made, so this experiment did not "
            "exercise any failure. A passing faulted run here is not evidence of resilience."
        )
    elif faulted.outcome is RunOutcome.PASS:
        verdict = ComparisonVerdict.RESILIENT
        explanation = "Faults were injected and every invariant still held."
    else:
        broken = [
            delta.invariant_id for delta in deltas if delta.faulted is not InvariantStatus.PASS
        ]
        verdict = ComparisonVerdict.DEGRADED
        explanation = (
            f"Faults were injected and the faulted run ended {faulted.outcome.value}; "
            f"invariants not satisfied: {', '.join(broken)}."
        )
        if faulted.agent.status.claims_success:
            explanation += " The agent nevertheless reported success."

    if unfired and verdict is not ComparisonVerdict.NOT_EXERCISED:
        explanation += f" Unfired fault rules: {', '.join(unfired)}."

    return Comparison(
        verdict=verdict,
        baseline_valid=baseline_valid,
        explanation=explanation,
        invariant_deltas=deltas,
        state_differences=differences,
        unfired_fault_rule_ids=unfired,
    )


def diff_states(
    baseline: dict[str, JsonValue], faulted: dict[str, JsonValue]
) -> tuple[StateDifference, ...]:
    """Return differences between two JSON documents in stable path order.

    A dict key or list element present on only one side is reported once, as a whole value,
    rather than as one difference per leaf.
    """

    differences: list[StateDifference] = []
    _diff(baseline, faulted, "", differences)
    return tuple(differences)


def _diff(left: JsonValue, right: JsonValue, path: str, out: list[StateDifference]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(left.keys() | right.keys()):
            child = f"{path}.{key}" if path else str(key)
            if key not in right:
                out.append(StateDifference(path=child, change="removed", baseline=left[key]))
            elif key not in left:
                out.append(StateDifference(path=child, change="added", faulted=right[key]))
            else:
                _diff(left[key], right[key], child, out)
    elif isinstance(left, list) and isinstance(right, list):
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(right):
                out.append(StateDifference(path=child, change="removed", baseline=left[index]))
            elif index >= len(left):
                out.append(StateDifference(path=child, change="added", faulted=right[index]))
            else:
                _diff(left[index], right[index], child, out)
    elif left != right:
        out.append(StateDifference(path=path, change="changed", baseline=left, faulted=right))


def _final_state(report: RunReport) -> dict[str, JsonValue]:
    snapshot = report.result.state_snapshot
    return dict(snapshot.state) if snapshot is not None else {}


def _invariant_deltas(
    baseline: Sequence[InvariantResult], faulted: Sequence[InvariantResult]
) -> tuple[InvariantDelta, ...]:
    baseline_by_id = {result.invariant_id: result.status for result in baseline}
    faulted_by_id = {result.invariant_id: result.status for result in faulted}
    ordered_ids = list(baseline_by_id) + [key for key in faulted_by_id if key not in baseline_by_id]
    return tuple(
        InvariantDelta(
            invariant_id=invariant_id,
            baseline=baseline_by_id.get(invariant_id),
            faulted=faulted_by_id.get(invariant_id),
        )
        for invariant_id in ordered_ids
    )
