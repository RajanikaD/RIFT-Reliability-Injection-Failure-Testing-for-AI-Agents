import asyncio
from decimal import Decimal

import pytest
from pydantic import JsonValue

from commerce_demo import CommerceSandbox
from rift_core import ExecutionContext, FaultRule, FaultType, RunMode
from rift_fault_engine import AmbiguousToolOutcomeError, FaultInjectingToolExecutor


def execution_context(run_id: str) -> ExecutionContext:
    return ExecutionContext(
        experiment_id="commerce-fault-test",
        run_id=run_id,
        seed=42,
        run_mode=RunMode.FAULTED,
    )


def timeout_rule() -> FaultRule:
    return FaultRule(
        fault_rule_id="refund-timeout-after-commit",
        tool_name="refund_payment",
        invocation_number=1,
        fault_type=FaultType.TIMEOUT_AFTER_COMMIT,
        error_message="refund response timed out",
    )


def invoke_refund(
    executor: FaultInjectingToolExecutor,
    sandbox: CommerceSandbox,
    *,
    run_id: str,
    idempotency_key: str | None = None,
) -> JsonValue:
    async def operation() -> JsonValue:
        refund = await sandbox.refund_payment(
            "PAY-1001",
            Decimal("79.99"),
            idempotency_key=idempotency_key,
        )
        return refund.model_dump(mode="json")

    return asyncio.run(
        executor.execute(
            tool_name="refund_payment",
            arguments={
                "payment_id": "PAY-1001",
                "amount": "79.99",
                "idempotency_key": idempotency_key,
            },
            operation=operation,
            execution_context=execution_context(run_id),
        )
    ).result


def test_ambiguous_refund_retry_is_unsafe_without_key_and_safe_with_key() -> None:
    sandbox = CommerceSandbox()
    unsafe_executor = FaultInjectingToolExecutor([timeout_rule()])

    with pytest.raises(AmbiguousToolOutcomeError) as unsafe_timeout:
        invoke_refund(unsafe_executor, sandbox, run_id="unsafe-run")

    unsafe_invocation = unsafe_timeout.value.invocation
    assert len(sandbox.snapshot().refunds) == 1
    assert unsafe_invocation.underlying_operation_executed is True
    assert unsafe_invocation.underlying_operation_committed is True

    invoke_refund(unsafe_executor, sandbox, run_id="unsafe-run")

    assert len(sandbox.snapshot().refunds) == 2

    sandbox.reset()
    safe_executor = FaultInjectingToolExecutor([timeout_rule()])

    with pytest.raises(AmbiguousToolOutcomeError) as safe_timeout:
        invoke_refund(
            safe_executor,
            sandbox,
            run_id="safe-run",
            idempotency_key="refund-ORD-1001",
        )

    safe_invocation = safe_timeout.value.invocation
    assert len(sandbox.snapshot().refunds) == 1
    assert safe_invocation.underlying_operation_executed is True
    assert safe_invocation.underlying_operation_committed is True

    retry_result = invoke_refund(
        safe_executor,
        sandbox,
        run_id="safe-run",
        idempotency_key="refund-ORD-1001",
    )

    assert retry_result["refund_id"] == "REF-0001"
    assert len(sandbox.snapshot().refunds) == 1
