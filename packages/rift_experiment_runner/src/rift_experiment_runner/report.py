"""Plain-text rendering of experiment reports. Derived only from the structured report."""

from __future__ import annotations

import json

from pydantic import JsonValue

from rift_core import InvariantStatus, ToolInvocation
from rift_experiment_runner.models import ExperimentReport, RunReport

_STATUS = {
    InvariantStatus.PASS: "PASS ",
    InvariantStatus.FAIL: "FAIL ",
    InvariantStatus.ERROR: "ERROR",
}


def render_text(report: ExperimentReport, *, show_trace: bool = True) -> str:
    experiment = report.experiment
    comparison = report.comparison
    lines = [
        f"RIFT experiment  {experiment.experiment_id}",
        f"  scenario  {experiment.scenario.scenario_id} v{experiment.scenario.version}",
        f"  agent     {report.adapter.name} v{report.adapter.version}",
        f"  seed      {experiment.seed}",
        "  faults    "
        + (
            ", ".join(
                f"{rule.fault_rule_id} ({rule.fault_type.value} on "
                f"{rule.tool_name} #{rule.invocation_number})"
                for rule in experiment.fault_rules
            )
            or "none"
        ),
        "",
        f"VERDICT: {comparison.verdict.value.upper()}",
        f"  {comparison.explanation}",
        "",
    ]
    for run in (report.baseline, report.faulted):
        lines.extend(_render_run(run, show_trace=show_trace))
        lines.append("")

    lines.append("Invariants (baseline -> faulted)")
    for delta in comparison.invariant_deltas:
        marker = "  " if not delta.changed else "! "
        lines.append(
            f"  {marker}{delta.invariant_id:<24} "
            f"{_status(delta.baseline)} -> {_status(delta.faulted)}"
        )
    failing = report.failing_invariants()
    if failing:
        lines.append("")
        lines.append("Faulted-run invariant evidence")
        for result in failing:
            lines.append(f"  {result.invariant_id}: {result.message}")
            lines.append(
                f"    expected {_json(result.expected)}  observed {_json(result.observed)}"
            )
            if result.evidence:
                lines.append(f"    evidence {_json(result.evidence)}")
            if result.error:
                lines.append(f"    error    {result.error}")

    lines.append("")
    lines.append("State differences (baseline vs faulted final state)")
    if not comparison.state_differences:
        lines.append("  none")
    for difference in comparison.state_differences:
        if difference.change == "added":
            lines.append(f"  + {difference.path} = {_json(difference.faulted)}")
        elif difference.change == "removed":
            lines.append(f"  - {difference.path} = {_json(difference.baseline)}")
        else:
            lines.append(
                f"  ~ {difference.path}: {_json(difference.baseline)} -> "
                f"{_json(difference.faulted)}"
            )
    return "\n".join(lines)


def _render_run(run: RunReport, *, show_trace: bool) -> list[str]:
    result = run.result
    passed = sum(item.status is InvariantStatus.PASS for item in result.invariant_results)
    lines = [
        f"{run.mode.value.upper()} run  outcome={result.outcome.value}  "
        f"invariants={passed}/{len(result.invariant_results)}  "
        f"agent={run.agent.status.value}  classification={run.classification.value}",
        f"  agent says: {run.agent.final_message or '(nothing)'}",
        f"  fingerprint {run.fingerprint[:16]}",
    ]
    if show_trace:
        lines.append("  trace:")
        for index, invocation in enumerate(result.tool_invocations, start=1):
            lines.append(f"    {index:>2}. {_render_invocation(invocation)}")
    return lines


def _render_invocation(invocation: ToolInvocation) -> str:
    call = f"{invocation.tool_name}#{invocation.invocation_number}"
    fault = f" [{invocation.fault_type.value}]" if invocation.fault_type else ""
    if not invocation.underlying_operation_executed:
        actual = "not executed"
    elif invocation.underlying_error is not None:
        actual = "executed, raised"
    elif (invocation.underlying_execution_count or 0) > 1:
        actual = f"executed x{invocation.underlying_execution_count}"
    else:
        actual = "executed"
    seen = "caller saw error" if invocation.caller_error is not None else "caller saw success"
    return f"{call:<22}{fault:<24} actual: {actual:<18} {seen}"


def _status(status: InvariantStatus | None) -> str:
    return _STATUS[status] if status is not None else "-    "


def _json(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True)
