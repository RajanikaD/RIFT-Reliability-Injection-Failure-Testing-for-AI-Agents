"""Tests that pin down RIFT's guarantees at their edges, including documented limitations.

Several tests here assert *current* behavior that is a limitation, not a goal. Each says so, so a
future change that removes the limitation updates the test deliberately.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from commerce_demo import CommerceSandbox
from commerce_demo.agents import reconciling_agent, retrying_agent
from commerce_demo.fault_cases import FAULT_CASES
from commerce_demo.invariants import commerce_cancellation_invariants
from commerce_demo.models import CommerceSnapshot
from commerce_demo.scenario import (
    CommerceEnvironment,
    CommerceScenarioBinding,
    commerce_experiment,
)
from rift_core import (
    AgentStatus,
    AgentTask,
    ExecutionContext,
    FaultRule,
    FaultType,
    InvariantResult,
    RunMode,
    RunOutcome,
    ScenarioSpec,
)
from rift_experiment_runner import (
    ComparisonVerdict,
    ExecutorToolGateway,
    ExperimentReport,
    ExperimentRunner,
    OutcomeClassification,
)
from rift_fault_engine import FaultInjectingToolExecutor, InMemoryInvocationRecorder
from rift_invariant_engine import Invariant, InvariantEvaluationContext

CONTEXT = ExecutionContext(
    experiment_id="limits", run_id="limits:faulted", seed=0, run_mode=RunMode.FAULTED
)


class NoSleep:
    async def sleep(self, seconds: float) -> None:
        return None


def run_experiment(experiment, adapter, binding=None) -> ExperimentReport:
    runner = ExperimentRunner(sleeper=NoSleep())
    return asyncio.run(runner.run(experiment, binding or CommerceScenarioBinding(), adapter))


# --- Concurrent duplicate requests -------------------------------------------------------------


def test_concurrent_same_key_refunds_create_one_refund_in_the_in_memory_sandbox() -> None:
    """Holds because the sandbox's check-and-write has no await point between them.

    LIMITATION: this is a property of the single-threaded in-memory repository, not of RIFT. A real
    store needs a unique constraint or transaction on the idempotency key to give the same result.
    """

    sandbox = CommerceSandbox()

    async def scenario() -> None:
        await asyncio.gather(
            *(
                sandbox.refund_payment("PAY-1001", Decimal("79.99"), idempotency_key="k")
                for _ in range(5)
            )
        )

    asyncio.run(scenario())
    assert len(sandbox.snapshot().refunds) == 1


def test_concurrent_requests_without_key_each_create_a_refund() -> None:
    sandbox = CommerceSandbox()

    async def scenario() -> None:
        await asyncio.gather(
            *(sandbox.refund_payment("PAY-1001", Decimal("79.99")) for _ in range(3))
        )

    asyncio.run(scenario())
    assert len(sandbox.snapshot().refunds) == 3


def test_reconciliation_misattributes_a_concurrent_writers_change() -> None:
    """LIMITATION of delta-based reconciliation: it cannot tell its own write from another's.

    The reconciling agent's restore times out *before* executing. Meanwhile another writer (say,
    a warehouse return) adds one unit. The agent re-probes, sees the increase, concludes its own
    restore applied, and skips the retry. Final stock is 10 where 11 is correct. Reconciliation is
    only sound when the agent is the sole writer, or when it can match on an operation identifier.
    """

    environment = CommerceEnvironment()
    handlers = dict(environment.tool_handlers())
    probe = handlers["get_inventory"]
    probes = 0

    async def probe_with_concurrent_writer(arguments: dict[str, JsonValue]) -> JsonValue:
        nonlocal probes
        probes += 1
        if probes == 2:  # the other writer lands between the agent's attempt and its re-probe
            await handlers["restore_inventory"]({"sku": "SKU-HEADPHONES-001", "quantity": 1})
        return await probe(arguments)

    handlers["get_inventory"] = probe_with_concurrent_writer
    executor = FaultInjectingToolExecutor(
        [
            FaultRule(
                fault_rule_id="restore-timeout",
                tool_name="restore_inventory",
                invocation_number=1,
                fault_type=FaultType.TIMEOUT_BEFORE_CALL,
            )
        ]
    )
    gateway = ExecutorToolGateway(
        executor=executor,
        handlers=handlers,
        specs=environment.tool_specs(),
        execution_context=CONTEXT,
        max_tool_calls=50,
    )
    task = AgentTask(scenario_id="commerce.cancel_order", instruction="cancel")
    output = asyncio.run(reconciling_agent().run(task, gateway))

    assert output.status is AgentStatus.COMPLETED
    assert "reconciled" in json.dumps(output.metadata["transcript"])
    assert environment.snapshot().inventory[0].available_quantity == 10  # 11 would be correct


def test_concurrent_invocations_are_numbered_by_start_and_recorded_by_completion() -> None:
    """Invocation numbers follow call start order; the recorder (and report trace) follows
    completion order. LIMITATION: there is no run-global start sequence field yet (audit D5)."""

    recorder = InMemoryInvocationRecorder()
    executor = FaultInjectingToolExecutor(
        [
            FaultRule(
                fault_rule_id="first",
                tool_name="slow",
                invocation_number=1,
                fault_type=FaultType.MALFORMED_RESPONSE,
                replacement_response="faulted",
            )
        ],
        recorder=recorder,
    )

    async def call(delay_ticks: int) -> JsonValue:
        async def operation() -> JsonValue:
            for _ in range(delay_ticks):
                await asyncio.sleep(0)
            return delay_ticks

        execution = await executor.execute(
            tool_name="slow", arguments={}, operation=operation, execution_context=CONTEXT
        )
        return execution.result

    async def scenario() -> list[JsonValue]:
        return list(await asyncio.gather(call(5), call(0)))

    results = asyncio.run(scenario())
    assert results == ["faulted", 0]  # the rule hit the call that *started* first
    assert [i.invocation_number for i in recorder.records] == [2, 1]


# --- Ambiguous commits -------------------------------------------------------------------------


def test_genuine_failure_after_partial_commit_is_recorded_as_unknown_and_caught_by_state() -> None:
    """A dependency that commits and then fails (no RIFT fault) is the hardest real ambiguity.

    The executor cannot know the commit happened, so it records ``committed=None`` and does not
    label it as injected. The invariants still see the committed refund in state.
    """

    sandbox = CommerceSandbox()
    recorder = InMemoryInvocationRecorder()
    executor = FaultInjectingToolExecutor([], recorder=recorder)

    async def commit_then_drop_connection() -> JsonValue:
        await sandbox.refund_payment("PAY-1001", Decimal("79.99"))
        raise ConnectionResetError("connection reset by peer")

    async def scenario() -> None:
        try:
            await executor.execute(
                tool_name="refund_payment",
                arguments={},
                operation=commit_then_drop_connection,
                execution_context=CONTEXT,
            )
        except ConnectionResetError:
            pass

    asyncio.run(scenario())
    record = recorder.records[0]
    assert record.underlying_operation_executed is True
    assert record.underlying_operation_committed is None  # unknown, not False
    assert record.fault_type is None
    assert len(sandbox.snapshot().refunds) == 1


def test_timeout_after_commit_records_a_committed_operation_the_caller_never_saw() -> None:
    report = run_experiment(
        commerce_experiment("ambiguous", FAULT_CASES["refund-timeout-after-commit"].rules),
        reconciling_agent(),
    )
    first = report.faulted.result.tool_invocations[1]
    assert first.tool_name == "refund_payment"
    assert (first.underlying_operation_committed, first.caller_error is not None) == (True, True)
    assert isinstance(first.underlying_result, dict)
    assert first.caller_response is None


# --- Invalid baselines -------------------------------------------------------------------------


class _BrokenInvariant:
    name = "broken"
    description = "Raises during evaluation."

    def evaluate(self, context: InvariantEvaluationContext[CommerceSnapshot]) -> InvariantResult:
        raise KeyError("missing field")


class _BindingWithBrokenInvariant:
    def __init__(self) -> None:
        names = (*(i.name for i in commerce_cancellation_invariants()), "broken")
        self._spec = CommerceScenarioBinding().spec.model_copy(update={"invariant_ids": names})

    @property
    def spec(self) -> ScenarioSpec:
        return self._spec

    def create_environment(self) -> CommerceEnvironment:
        return CommerceEnvironment()

    def invariants(self) -> Sequence[Invariant[CommerceSnapshot]]:
        return (*commerce_cancellation_invariants(), _BrokenInvariant())


def test_baseline_evaluation_error_invalidates_the_comparison() -> None:
    experiment = commerce_experiment(
        "broken-eval", FAULT_CASES["refund-timeout-after-commit"].rules
    ).model_copy(update={"scenario": _BindingWithBrokenInvariant().spec})
    report = run_experiment(experiment, reconciling_agent(), _BindingWithBrokenInvariant())

    assert report.baseline.outcome is RunOutcome.ERROR
    assert report.baseline.classification is OutcomeClassification.EVALUATION_ERROR
    assert report.comparison.verdict is ComparisonVerdict.BASELINE_INVALID
    broken = report.baseline.result.invariant_results[-1]
    assert broken.error == "KeyError: 'missing field'"


# --- Never-triggered faults --------------------------------------------------------------------


def test_fault_on_a_declared_tool_the_agent_never_calls_is_not_exercised() -> None:
    rule = FaultRule(
        fault_rule_id="unused-tool",
        tool_name="list_refunds",
        invocation_number=1,
        fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
    )
    report = run_experiment(commerce_experiment("never", [rule]), retrying_agent())
    assert report.comparison.verdict is ComparisonVerdict.NOT_EXERCISED
    assert report.faulted.fired_fault_rule_ids == ()


def test_fault_on_an_undeclared_tool_is_rejected_at_definition_time() -> None:
    rule = FaultRule(
        fault_rule_id="ghost",
        tool_name="delete_database",
        invocation_number=1,
        fault_type=FaultType.EXCEPTION,
    )
    try:
        commerce_experiment("ghost", [rule])
    except ValueError as error:
        assert "undeclared tools" in str(error)
    else:  # pragma: no cover
        raise AssertionError("undeclared tool was accepted")


# --- Reproducibility ---------------------------------------------------------------------------

TIMING_KEYS = {"started_at", "finished_at", "duration_ms", "captured_at"}


def _strip_timing(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_timing(v) for k, v in value.items() if k not in TIMING_KEYS}
    if isinstance(value, list):
        return [_strip_timing(v) for v in value]
    return value


def test_reports_are_identical_apart_from_timing_fields() -> None:
    experiment = commerce_experiment("repro", FAULT_CASES["refund-duplicate-request"].rules)
    first = json.loads(run_experiment(experiment, retrying_agent()).model_dump_json())
    second = json.loads(run_experiment(experiment, retrying_agent()).model_dump_json())
    assert first != second  # wall-clock timestamps differ...
    assert _strip_timing(first) == _strip_timing(second)  # ...nothing else does.


def test_fingerprints_are_stable_across_processes_and_hash_seeds(tmp_path: Path) -> None:
    fingerprints = []
    for hash_seed in ("0", "12345"):
        output = tmp_path / f"report-{hash_seed}.json"
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        subprocess.run(
            [
                sys.executable,
                "-m",
                "rift_cli",
                "run",
                "--agent",
                "reconciling",
                "--fault",
                "inventory-timeout-after-commit",
                "--json",
                str(output),
            ],
            check=True,
            capture_output=True,
            env=env,
        )
        report = json.loads(output.read_text(encoding="utf-8"))
        fingerprints.append((report["baseline"]["fingerprint"], report["faulted"]["fingerprint"]))
    assert fingerprints[0] == fingerprints[1]
