from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from rift_core import (
    ExecutionContext,
    ExperimentRunResult,
    ExperimentSpec,
    FaultPhase,
    FaultRule,
    FaultType,
    InvariantResult,
    InvariantStatus,
    RunMode,
    RunOutcome,
    ScenarioSpec,
    StateSnapshot,
    ToolInvocation,
)


def make_scenario() -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="scenario-1",
        name="Framework-neutral scenario",
        task="Perform the requested operation.",
        initial_state={"resource": {"status": "ready"}},
        tool_names=("update_resource",),
        invariant_ids=("resource-updated",),
    )


def make_exception_rule(**overrides: object) -> FaultRule:
    values: dict[str, object] = {
        "fault_rule_id": "rule-1",
        "tool_name": "update_resource",
        "invocation_number": 1,
        "fault_type": FaultType.EXCEPTION,
        "error_message": "dependency unavailable",
    }
    values.update(overrides)
    return FaultRule.model_validate(values)


def invocation_timing() -> dict[str, object]:
    timestamp = datetime(2026, 9, 18, tzinfo=UTC)
    return {
        "started_at": timestamp,
        "finished_at": timestamp,
        "duration_ms": 0.0,
    }


def test_valid_domain_model_construction() -> None:
    scenario = make_scenario()
    rule = make_exception_rule()
    experiment = ExperimentSpec(
        experiment_id="experiment-1",
        name="Deterministic failure test",
        scenario=scenario,
        seed=42,
        fault_rules=(rule,),
    )

    assert experiment.scenario == scenario
    assert experiment.fault_rules == (rule,)
    assert rule.phase is FaultPhase.BEFORE_CALL
    assert rule.underlying_operation_executes is False


@pytest.mark.parametrize(
    ("values", "expected_message"),
    [
        (
            {
                "fault_rule_id": "latency",
                "tool_name": "update_resource",
                "invocation_number": 1,
                "fault_type": FaultType.LATENCY,
            },
            "latency faults require delay_ms",
        ),
        (
            {
                "fault_rule_id": "latency",
                "tool_name": "update_resource",
                "invocation_number": 1,
                "fault_type": FaultType.LATENCY,
                "delay_ms": 0,
            },
            "greater than 0",
        ),
        (
            {
                "fault_rule_id": "malformed",
                "tool_name": "update_resource",
                "invocation_number": 1,
                "fault_type": FaultType.MALFORMED_RESPONSE,
            },
            "malformed-response faults require replacement_response",
        ),
        (
            {
                "fault_rule_id": "bad-invocation",
                "tool_name": "update_resource",
                "invocation_number": 0,
                "fault_type": FaultType.EXCEPTION,
            },
            "greater than 0",
        ),
        (
            {
                "fault_rule_id": "wrong-phase",
                "tool_name": "update_resource",
                "invocation_number": 1,
                "fault_type": FaultType.TIMEOUT_AFTER_COMMIT,
                "phase": FaultPhase.BEFORE_CALL,
            },
            "must use the after_call phase",
        ),
    ],
)
def test_invalid_fault_configurations_fail_early(
    values: dict[str, object], expected_message: str
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        FaultRule.model_validate(values)


def test_experiment_rejects_duplicate_rule_targets() -> None:
    first = make_exception_rule(fault_rule_id="first")
    second = make_exception_rule(fault_rule_id="second")

    with pytest.raises(ValidationError, match="only one fault rule"):
        ExperimentSpec(
            experiment_id="experiment-1",
            name="Invalid experiment",
            scenario=make_scenario(),
            seed=42,
            fault_rules=(first, second),
        )


def test_fault_rule_matching_is_deterministic() -> None:
    rule = make_exception_rule()

    results = [
        rule.matches(
            tool_name="update_resource",
            invocation_number=1,
            run_mode=RunMode.FAULTED,
        )
        for _ in range(10)
    ]

    assert results == [True] * 10


def test_fault_rule_matches_only_the_configured_invocation_number() -> None:
    rule = make_exception_rule(invocation_number=2)

    assert not rule.matches(
        tool_name="update_resource",
        invocation_number=1,
        run_mode=RunMode.FAULTED,
    )
    assert rule.matches(
        tool_name="update_resource",
        invocation_number=2,
        run_mode=RunMode.FAULTED,
    )
    assert not rule.matches(
        tool_name="another_tool",
        invocation_number=2,
        run_mode=RunMode.FAULTED,
    )


def test_baseline_run_never_matches_fault_rules() -> None:
    rule = make_exception_rule()

    assert not rule.matches(
        tool_name="update_resource",
        invocation_number=1,
        run_mode=RunMode.BASELINE,
    )


def test_experiment_spec_serialization_round_trip() -> None:
    experiment = ExperimentSpec(
        experiment_id="experiment-1",
        name="Serializable experiment",
        scenario=make_scenario(),
        seed=42,
        fault_rules=(
            FaultRule(
                fault_rule_id="malformed",
                tool_name="update_resource",
                invocation_number=1,
                fault_type=FaultType.MALFORMED_RESPONSE,
                replacement_response={"unexpected": ["shape"]},
            ),
        ),
    )

    restored = ExperimentSpec.model_validate_json(experiment.model_dump_json())

    assert restored == experiment
    assert restored.fault_rules[0].phase is FaultPhase.AFTER_CALL


def test_run_result_serialization_round_trip() -> None:
    context = ExecutionContext(
        experiment_id="experiment-1",
        run_id="run-1",
        seed=42,
        run_mode=RunMode.BASELINE,
    )
    snapshot = StateSnapshot(
        snapshot_id="snapshot-1",
        run_id="run-1",
        captured_at=datetime(2026, 9, 18, tzinfo=UTC),
        state={"resource": {"status": "updated"}},
    )
    result = ExperimentRunResult(
        context=context,
        outcome=RunOutcome.PASS,
        state_snapshot=snapshot,
        invariant_results=(
            InvariantResult(
                invariant_id="resource-updated",
                status=InvariantStatus.PASS,
                message="Resource is updated.",
                expected="updated",
                observed="updated",
            ),
        ),
    )

    restored = ExperimentRunResult.model_validate_json(result.model_dump_json())

    assert restored == result


def test_timeout_before_call_prevents_underlying_operation() -> None:
    rule = FaultRule(
        fault_rule_id="before-timeout",
        tool_name="update_resource",
        invocation_number=1,
        fault_type=FaultType.TIMEOUT_BEFORE_CALL,
        error_message="request timed out",
    )
    invocation = ToolInvocation(
        invocation_id="invocation-1",
        run_id="run-1",
        tool_name="update_resource",
        invocation_number=1,
        fault_rule_id=rule.fault_rule_id,
        fault_type=rule.fault_type,
        **invocation_timing(),
        underlying_operation_executed=False,
        underlying_operation_committed=False,
        caller_error="request timed out",
    )

    assert rule.phase is FaultPhase.BEFORE_CALL
    assert rule.underlying_operation_executes is False
    assert rule.commits_before_caller_error is False
    assert invocation.fault_phase is FaultPhase.BEFORE_CALL
    assert invocation.underlying_operation_executed is False
    assert invocation.underlying_operation_committed is False


def test_timeout_before_call_rejects_executed_operation() -> None:
    with pytest.raises(ValidationError, match="cannot execute or commit"):
        ToolInvocation(
            invocation_id="invocation-1",
            run_id="run-1",
            tool_name="update_resource",
            invocation_number=1,
            fault_rule_id="before-timeout",
            fault_type=FaultType.TIMEOUT_BEFORE_CALL,
            **invocation_timing(),
            underlying_operation_executed=True,
            underlying_operation_committed=False,
            caller_error="request timed out",
        )


def test_timeout_after_commit_hides_committed_success() -> None:
    rule = FaultRule(
        fault_rule_id="after-timeout",
        tool_name="update_resource",
        invocation_number=1,
        fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
        error_message="response timed out",
    )
    invocation = ToolInvocation(
        invocation_id="invocation-1",
        run_id="run-1",
        tool_name="update_resource",
        invocation_number=1,
        fault_rule_id=rule.fault_rule_id,
        fault_type=rule.fault_type,
        **invocation_timing(),
        underlying_operation_executed=True,
        underlying_operation_committed=True,
        underlying_result={"status": "success"},
        caller_error="response timed out",
    )

    assert rule.phase is FaultPhase.AFTER_CALL
    assert rule.underlying_operation_executes is True
    assert rule.commits_before_caller_error is True
    assert invocation.fault_phase is FaultPhase.AFTER_CALL
    assert invocation.underlying_operation_executed is True
    assert invocation.underlying_operation_committed is True
    assert invocation.caller_response is None
    assert invocation.caller_error == "response timed out"


def test_timeout_after_commit_rejects_uncommitted_operation() -> None:
    with pytest.raises(ValidationError, match="requires an executed, committed operation"):
        ToolInvocation(
            invocation_id="invocation-1",
            run_id="run-1",
            tool_name="update_resource",
            invocation_number=1,
            fault_rule_id="after-timeout",
            fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
            **invocation_timing(),
            underlying_operation_executed=True,
            underlying_operation_committed=False,
            caller_error="response timed out",
        )
