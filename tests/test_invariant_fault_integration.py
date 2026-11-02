import asyncio
from decimal import Decimal

import pytest
from pydantic import JsonValue

from commerce_demo import CommerceSandbox, commerce_cancellation_invariants
from rift_core import ExecutionContext, FaultRule, FaultType, InvariantStatus, RunMode
from rift_fault_engine import AmbiguousToolOutcomeError, FaultInjectingToolExecutor
from rift_invariant_engine import InvariantEvaluationContext, InvariantEvaluator


def context(run_id: str) -> ExecutionContext:
    return ExecutionContext(
        experiment_id="invariant-integration",
        run_id=run_id,
        seed=42,
        run_mode=RunMode.FAULTED,
    )


async def refund_through_executor(
    executor: FaultInjectingToolExecutor,
    sandbox: CommerceSandbox,
    execution_context: ExecutionContext,
    *,
    idempotency_key: str | None,
) -> JsonValue:
    async def operation() -> JsonValue:
        refund = await sandbox.refund_payment(
            "PAY-1001",
            Decimal("79.99"),
            idempotency_key=idempotency_key,
        )
        return refund.model_dump(mode="json")

    execution = await executor.execute(
        tool_name="refund_payment",
        arguments={
            "payment_id": "PAY-1001",
            "amount": "79.99",
            "idempotency_key": idempotency_key,
        },
        operation=operation,
        execution_context=execution_context,
    )
    return execution.result


async def run_ambiguous_refund_scenario(*, idempotency_key: str | None):
    sandbox = CommerceSandbox()
    before = sandbox.snapshot()
    execution_context = context("safe" if idempotency_key else "unsafe")
    rule = FaultRule(
        fault_rule_id="refund-timeout",
        tool_name="refund_payment",
        invocation_number=1,
        fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
        error_message="refund response timed out",
    )
    executor = FaultInjectingToolExecutor([rule])

    await sandbox.cancel_order("ORD-1001")
    with pytest.raises(AmbiguousToolOutcomeError):
        await refund_through_executor(
            executor,
            sandbox,
            execution_context,
            idempotency_key=idempotency_key,
        )
    await refund_through_executor(
        executor,
        sandbox,
        execution_context,
        idempotency_key=idempotency_key,
    )
    await sandbox.restore_inventory("SKU-HEADPHONES-001", 1)
    await sandbox.send_confirmation("ORD-1001", "Cancellation confirmed.")

    return InvariantEvaluator(commerce_cancellation_invariants()).evaluate(
        InvariantEvaluationContext(
            before_state=before,
            after_state=sandbox.snapshot(),
        )
    )


def test_unsafe_retry_after_ambiguous_timeout_produces_incorrect_final_state() -> None:
    summary = asyncio.run(run_ambiguous_refund_scenario(idempotency_key=None))

    assert [result.status for result in summary.results] == [
        InvariantStatus.PASS,
        InvariantStatus.FAIL,
        InvariantStatus.FAIL,
        InvariantStatus.PASS,
        InvariantStatus.PASS,
    ]
    assert summary.all_passed is False


def test_stable_idempotency_key_after_ambiguous_timeout_preserves_correct_state() -> None:
    summary = asyncio.run(run_ambiguous_refund_scenario(idempotency_key="refund-ORD-1001"))

    assert [result.status for result in summary.results] == [InvariantStatus.PASS] * 5
    assert summary.all_passed is True
