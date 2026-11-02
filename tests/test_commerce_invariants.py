import asyncio
from decimal import Decimal

import pytest

from commerce_demo import CommerceSandbox, CommerceSnapshot, commerce_cancellation_invariants
from rift_core import InvariantStatus
from rift_invariant_engine import (
    InvariantEvaluationContext,
    InvariantEvaluationSummary,
    InvariantEvaluator,
)


async def complete_scenario(
    sandbox: CommerceSandbox,
    *,
    refund_count: int = 1,
    inventory_quantity: int = 1,
    confirmation_count: int = 1,
) -> None:
    await sandbox.cancel_order("ORD-1001")
    for _ in range(refund_count):
        await sandbox.refund_payment("PAY-1001", Decimal("79.99"))
    if inventory_quantity:
        await sandbox.restore_inventory("SKU-HEADPHONES-001", inventory_quantity)
    for _ in range(confirmation_count):
        await sandbox.send_confirmation("ORD-1001", "Your order was cancelled.")


def evaluate(sandbox: CommerceSandbox, before: CommerceSnapshot) -> InvariantEvaluationSummary:
    context = InvariantEvaluationContext(
        before_state=before,
        after_state=sandbox.snapshot(),
        evidence={"agent_output": "Order cancelled and refund completed successfully."},
    )
    return InvariantEvaluator(commerce_cancellation_invariants()).evaluate(context)


def statuses(summary: InvariantEvaluationSummary) -> dict[str, InvariantStatus]:
    return {result.invariant_id: result.status for result in summary.results}


def test_order_cancelled_passes_and_fails() -> None:
    unchanged = CommerceSandbox()
    before = unchanged.snapshot()
    failed = evaluate(unchanged, before)

    changed = CommerceSandbox()
    changed_before = changed.snapshot()
    asyncio.run(changed.cancel_order("ORD-1001"))
    passed = evaluate(changed, changed_before)

    assert statuses(failed)["order_cancelled"] is InvariantStatus.FAIL
    assert statuses(passed)["order_cancelled"] is InvariantStatus.PASS


@pytest.mark.parametrize(
    ("refund_count", "expected_count_status", "expected_amount_status"),
    [
        (1, InvariantStatus.PASS, InvariantStatus.PASS),
        (2, InvariantStatus.FAIL, InvariantStatus.FAIL),
    ],
)
def test_refund_count_and_amount_invariants(
    refund_count: int,
    expected_count_status: InvariantStatus,
    expected_amount_status: InvariantStatus,
) -> None:
    sandbox = CommerceSandbox()
    before = sandbox.snapshot()
    for _ in range(refund_count):
        asyncio.run(sandbox.refund_payment("PAY-1001", Decimal("79.99")))

    summary = evaluate(sandbox, before)

    assert statuses(summary)["exactly_one_refund"] is expected_count_status
    assert statuses(summary)["refund_amount_correct"] is expected_amount_status


@pytest.mark.parametrize(
    ("increase", "expected_status"),
    [
        (1, InvariantStatus.PASS),
        (0, InvariantStatus.FAIL),
        (2, InvariantStatus.FAIL),
    ],
)
def test_inventory_must_increase_by_exactly_one(
    increase: int, expected_status: InvariantStatus
) -> None:
    sandbox = CommerceSandbox()
    before = sandbox.snapshot()
    if increase:
        asyncio.run(sandbox.restore_inventory("SKU-HEADPHONES-001", increase))

    result = next(
        result
        for result in evaluate(sandbox, before).results
        if result.invariant_id == "inventory_restored"
    )

    assert result.status is expected_status
    assert result.expected == 1
    assert result.observed == increase
    assert result.evidence == {
        "sku": "SKU-HEADPHONES-001",
        "before_quantity": 9,
        "after_quantity": 9 + increase,
    }


@pytest.mark.parametrize(
    ("confirmation_count", "expected_status"),
    [
        (1, InvariantStatus.PASS),
        (0, InvariantStatus.FAIL),
        (2, InvariantStatus.FAIL),
    ],
)
def test_single_confirmation_passes_only_for_one_record(
    confirmation_count: int, expected_status: InvariantStatus
) -> None:
    sandbox = CommerceSandbox()
    before = sandbox.snapshot()
    for _ in range(confirmation_count):
        asyncio.run(sandbox.send_confirmation("ORD-1001", "Cancellation confirmed."))

    assert statuses(evaluate(sandbox, before))["single_confirmation"] is expected_status


def test_full_successful_commerce_scenario_passes_all_invariants() -> None:
    sandbox = CommerceSandbox()
    before = sandbox.snapshot()
    asyncio.run(complete_scenario(sandbox))

    summary = evaluate(sandbox, before)

    assert summary.all_passed is True
    assert summary.passed == 5


def test_duplicate_refund_and_misleading_agent_text_do_not_mask_bad_state() -> None:
    sandbox = CommerceSandbox()
    before = sandbox.snapshot()
    asyncio.run(complete_scenario(sandbox, refund_count=2))

    summary = evaluate(sandbox, before)

    assert [result.status for result in summary.results] == [
        InvariantStatus.PASS,
        InvariantStatus.FAIL,
        InvariantStatus.FAIL,
        InvariantStatus.PASS,
        InvariantStatus.PASS,
    ]
    assert summary.all_passed is False


def test_evaluation_does_not_mutate_snapshots() -> None:
    sandbox = CommerceSandbox()
    before = sandbox.snapshot()
    asyncio.run(complete_scenario(sandbox))
    after = sandbox.snapshot()
    before_json = before.model_dump_json()
    after_json = after.model_dump_json()

    InvariantEvaluator(commerce_cancellation_invariants()).evaluate(
        InvariantEvaluationContext(before_state=before, after_state=after)
    )

    assert before.model_dump_json() == before_json
    assert after.model_dump_json() == after_json
