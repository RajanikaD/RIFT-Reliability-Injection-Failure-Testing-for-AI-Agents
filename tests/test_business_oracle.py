"""Independent business oracle for the full agent x fault matrix.

This module deliberately does not import ``commerce_demo.invariants`` or reuse its selectors. The
rules below are re-derived from the task text ("Cancel order ORD-1001, refund the customer,
restore inventory, and send confirmation") and the documented fixture, and are checked against
the raw JSON final state and raw invocation evidence in each report. If RIFT's own invariants and
this oracle ever disagree, one of them is wrong.

Business rules
--------------
R1  Order ORD-1001 ends ``cancelled``.
R2  Payment PAY-1001 has exactly one refund, of exactly 79.99.
R3  Total refunded for PAY-1001 never exceeds the captured 79.99 (no over-refund).
R4  SKU-HEADPHONES-001 inventory ends exactly one higher than it started.
R5  Exactly one cancellation confirmation exists for ORD-1001.

Consistency rules (must hold in every run, pass or fail)
--------------------------------------------------------
C1  Payment status is ``refunded`` if and only if at least one refund exists.
C2  No orders, payments or SKUs are created or deleted.
C3  Every refund and notification in final state is explained by an executed invocation in the
    trace, and every one the trace claims was created exists (trace <-> state agreement).
C4  The inventory change equals the number of successful restore executions in the trace.
C5  Invocations with a before-call fault did not execute.
C6  Baseline runs contain no injected faults.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from commerce_demo.agents import AGENT_PROFILES
from commerce_demo.fault_cases import FAULT_CASES
from commerce_demo.scenario import CommerceScenarioBinding, commerce_experiment
from rift_core import AgentStatus, FaultType, RunOutcome, ToolInvocation
from rift_experiment_runner import ExperimentReport, ExperimentRunner, RunReport

ORDER, PAYMENT, SKU = "ORD-1001", "PAY-1001", "SKU-HEADPHONES-001"
CAPTURED = Decimal("79.99")
BEFORE_CALL_FAULTS = {FaultType.EXCEPTION, FaultType.RATE_LIMIT, FaultType.TIMEOUT_BEFORE_CALL}


class NoSleep:
    async def sleep(self, seconds: float) -> None:
        return None


@pytest.fixture(scope="module")
def matrix() -> dict[tuple[str, str], ExperimentReport]:
    runner = ExperimentRunner(sleeper=NoSleep())
    reports = {}
    for agent in AGENT_PROFILES:
        for case_name, case in FAULT_CASES.items():
            experiment = commerce_experiment(f"oracle-{agent}-{case_name}", case.rules)
            reports[(agent, case_name)] = asyncio.run(
                runner.run(experiment, CommerceScenarioBinding(), AGENT_PROFILES[agent]())
            )
    return reports


def final(run: RunReport) -> dict[str, Any]:
    assert run.result.state_snapshot is not None
    return dict(run.result.state_snapshot.state)


def business_rules(run: RunReport) -> dict[str, bool]:
    state, initial = final(run), run.initial_state
    order = next(o for o in state["orders"] if o["order_id"] == ORDER)
    refunds = [r for r in state["refunds"] if r["payment_id"] == PAYMENT]
    refunded = sum((Decimal(r["amount"]) for r in refunds), Decimal("0"))
    stock_before = next(i for i in initial["inventory"] if i["sku"] == SKU)["available_quantity"]
    stock_after = next(i for i in state["inventory"] if i["sku"] == SKU)["available_quantity"]
    confirmations = [
        n
        for n in state["notifications"]
        if n["order_id"] == ORDER and n["notification_type"] == "cancellation_confirmation"
    ]
    return {
        "R1": order["status"] == "cancelled",
        "R2": len(refunds) == 1 and Decimal(refunds[0]["amount"]) == CAPTURED,
        "R3": refunded <= CAPTURED,
        "R4": stock_after - stock_before == 1,
        "R5": len(confirmations) == 1,
    }


def created_ids(invocations: tuple[ToolInvocation, ...], tool: str, key: str) -> set[str]:
    ids: set[str] = set()
    for invocation in invocations:
        if invocation.tool_name != tool or invocation.underlying_result is None:
            continue
        results = invocation.underlying_result
        deliveries = results if (invocation.underlying_execution_count or 0) > 1 else [results]
        assert isinstance(deliveries, list)
        for delivered in deliveries:
            if isinstance(delivered, dict) and key in delivered:
                ids.add(str(delivered[key]))
    return ids


def successful_restores(invocations: tuple[ToolInvocation, ...]) -> int:
    total = 0
    for invocation in invocations:
        if invocation.tool_name != "restore_inventory" or invocation.underlying_result is None:
            continue
        if (invocation.underlying_execution_count or 0) > 1:
            assert isinstance(invocation.underlying_result, list)
            total += sum("error" not in item for item in invocation.underlying_result)  # type: ignore[operator]
        else:
            total += 1
    return total


def check_consistency(run: RunReport) -> None:
    state, initial = final(run), run.initial_state
    invocations = run.result.tool_invocations
    payment = next(p for p in state["payments"] if p["payment_id"] == PAYMENT)
    refund_ids = {r["refund_id"] for r in state["refunds"]}
    notification_ids = {n["notification_id"] for n in state["notifications"]}

    assert (payment["status"] == "refunded") == bool(refund_ids), "C1"
    for collection, key in (
        ("orders", "order_id"),
        ("payments", "payment_id"),
        ("inventory", "sku"),
    ):
        assert {e[key] for e in state[collection]} == {e[key] for e in initial[collection]}, "C2"
    assert refund_ids == created_ids(invocations, "refund_payment", "refund_id"), "C3 refunds"
    assert notification_ids == created_ids(invocations, "send_confirmation", "notification_id"), (
        "C3 notifications"
    )
    stock_before = next(i for i in initial["inventory"] if i["sku"] == SKU)["available_quantity"]
    stock_after = next(i for i in state["inventory"] if i["sku"] == SKU)["available_quantity"]
    assert stock_after - stock_before == successful_restores(invocations), "C4"
    for invocation in invocations:
        if invocation.fault_type in BEFORE_CALL_FAULTS:
            assert invocation.underlying_operation_executed is False, "C5"


def test_matrix_covers_every_agent_and_fault_case(matrix) -> None:
    assert len(matrix) == len(AGENT_PROFILES) * len(FAULT_CASES) == 40


def test_rift_outcome_agrees_with_independent_business_oracle(matrix) -> None:
    disagreements = []
    for (agent, case_name), report in matrix.items():
        for run in (report.baseline, report.faulted):
            rules = business_rules(run)
            oracle_pass = all(rules.values())
            if (run.outcome is RunOutcome.PASS) != oracle_pass:
                disagreements.append((agent, case_name, run.mode.value, rules))
    assert disagreements == []


def test_each_rift_invariant_agrees_with_the_matching_business_rule(matrix) -> None:
    mapping = {
        "order_cancelled": ("R1",),
        "exactly_one_refund": ("R2",),
        "refund_amount_correct": ("R2", "R3"),
        "inventory_restored": ("R4",),
        "single_confirmation": ("R5",),
    }
    for report in matrix.values():
        for run in (report.baseline, report.faulted):
            rules = business_rules(run)
            for result in run.result.invariant_results:
                expected = all(rules[rule] for rule in mapping[result.invariant_id])
                assert (result.status.value == "pass") == expected, (
                    run.result.context.run_id,
                    result.invariant_id,
                )


def test_trace_and_state_agree_in_every_run(matrix) -> None:
    for report in matrix.values():
        assert report.baseline.fired_fault_rule_ids == (), "C6"
        assert all(i.fault_type is None for i in report.baseline.result.tool_invocations), "C6"
        check_consistency(report.baseline)
        check_consistency(report.faulted)


def test_silent_failure_means_agent_claimed_success_over_broken_business_rules(matrix) -> None:
    for report in matrix.values():
        faulted = report.faulted
        claimed = faulted.agent.status is AgentStatus.COMPLETED
        broken = not all(business_rules(faulted).values())
        assert (faulted.classification.value == "silent_failure") == (claimed and broken)


def test_every_baseline_satisfies_the_business_rules(matrix) -> None:
    for report in matrix.values():
        assert all(business_rules(report.baseline).values())


def test_over_refund_happens_exactly_when_duplicates_occur(matrix) -> None:
    """R3 is not one of RIFT's invariants; it must still be caught via R2/refund_amount_correct."""

    for report in matrix.values():
        rules = business_rules(report.faulted)
        if not rules["R3"]:
            assert report.faulted.outcome is RunOutcome.FAIL
