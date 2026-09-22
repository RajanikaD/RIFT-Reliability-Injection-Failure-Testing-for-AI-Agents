import asyncio
from collections.abc import Awaitable
from decimal import Decimal
from typing import TypeVar

import pytest

from commerce_demo import (
    CommerceSandbox,
    IdempotencyConflictError,
    InvalidInventoryQuantityError,
    InvalidRefundAmountError,
    InventoryItemNotFoundError,
    OrderNotFoundError,
    OrderStatus,
    PaymentNotFoundError,
    PaymentStatus,
)

T = TypeVar("T")


def run(awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)


def test_reset_recreates_exact_initial_state_after_multiple_mutations() -> None:
    sandbox = CommerceSandbox()
    initial = sandbox.snapshot()

    run(sandbox.cancel_order("ORD-1001"))
    run(sandbox.refund_payment("PAY-1001", Decimal("79.99")))
    run(sandbox.restore_inventory("SKU-HEADPHONES-001", 1))
    run(sandbox.send_confirmation("ORD-1001", "Order cancelled."))

    assert sandbox.snapshot() != initial

    sandbox.reset()

    assert sandbox.snapshot() == initial


def test_snapshot_is_detached_from_later_state_changes() -> None:
    sandbox = CommerceSandbox()
    original = sandbox.snapshot()

    run(sandbox.cancel_order("ORD-1001"))
    run(sandbox.refund_payment("PAY-1001", Decimal("79.99")))
    run(sandbox.restore_inventory("SKU-HEADPHONES-001", 1))

    assert original.orders[0].status is OrderStatus.CONFIRMED
    assert original.payments[0].status is PaymentStatus.CAPTURED
    assert original.refunds == ()
    assert original.inventory[0].available_quantity == 9


def test_get_order_returns_existing_order() -> None:
    order = run(CommerceSandbox().get_order("ORD-1001"))

    assert order.order_id == "ORD-1001"
    assert order.status is OrderStatus.CONFIRMED


def test_get_order_raises_typed_error_for_unknown_order() -> None:
    with pytest.raises(OrderNotFoundError, match="ORD-404"):
        run(CommerceSandbox().get_order("ORD-404"))


def test_cancel_order_is_idempotent() -> None:
    sandbox = CommerceSandbox()

    first = run(sandbox.cancel_order("ORD-1001"))
    second = run(sandbox.cancel_order("ORD-1001"))

    assert first.status is OrderStatus.CANCELLED
    assert second == first
    assert sandbox.snapshot().orders == (first,)


def test_normal_refund_creates_one_correct_record() -> None:
    sandbox = CommerceSandbox()

    refund = run(sandbox.refund_payment("PAY-1001", Decimal("79.99")))
    snapshot = sandbox.snapshot()

    assert refund.refund_id == "REF-0001"
    assert refund.amount == Decimal("79.99")
    assert snapshot.refunds == (refund,)
    assert snapshot.payments[0].status is PaymentStatus.REFUNDED


def test_duplicate_refund_without_idempotency_creates_two_side_effects() -> None:
    sandbox = CommerceSandbox()

    first = run(sandbox.refund_payment("PAY-1001", Decimal("79.99")))
    second = run(sandbox.refund_payment("PAY-1001", Decimal("79.99")))
    refunds = sandbox.snapshot().refunds

    assert first.refund_id == "REF-0001"
    assert second.refund_id == "REF-0002"
    assert len(refunds) == 2
    assert sum((refund.amount for refund in refunds), Decimal("0.00")) == Decimal("159.98")


def test_refund_with_same_idempotency_key_returns_original_refund() -> None:
    sandbox = CommerceSandbox()

    first = run(
        sandbox.refund_payment(
            "PAY-1001",
            Decimal("79.99"),
            idempotency_key="refund-ORD-1001",
        )
    )
    second = run(
        sandbox.refund_payment(
            "PAY-1001",
            Decimal("79.99"),
            idempotency_key="refund-ORD-1001",
        )
    )

    assert second == first
    assert len(sandbox.snapshot().refunds) == 1


def test_refund_idempotency_key_conflict_is_explicit() -> None:
    sandbox = CommerceSandbox()
    run(
        sandbox.refund_payment(
            "PAY-1001",
            Decimal("79.99"),
            idempotency_key="refund-key",
        )
    )

    with pytest.raises(IdempotencyConflictError, match="different request"):
        run(
            sandbox.refund_payment(
                "PAY-1001",
                Decimal("20.00"),
                idempotency_key="refund-key",
            )
        )


def test_refund_idempotency_key_is_normalized() -> None:
    sandbox = CommerceSandbox()

    first = run(
        sandbox.refund_payment(
            "PAY-1001",
            Decimal("79.99"),
            idempotency_key="  refund-key  ",
        )
    )
    second = run(
        sandbox.refund_payment(
            "PAY-1001",
            Decimal("79.99"),
            idempotency_key="refund-key",
        )
    )

    assert first == second
    assert first.idempotency_key == "refund-key"
    assert len(sandbox.snapshot().refunds) == 1


def test_unknown_payment_raises_typed_error() -> None:
    with pytest.raises(PaymentNotFoundError, match="PAY-404"):
        run(CommerceSandbox().refund_payment("PAY-404", Decimal("1.00")))


def test_inventory_restoration_increases_available_quantity() -> None:
    sandbox = CommerceSandbox()

    item = run(sandbox.restore_inventory("SKU-HEADPHONES-001", 1))

    assert item.available_quantity == 10
    assert sandbox.snapshot().inventory == (item,)


@pytest.mark.parametrize("quantity", [0, -1])
def test_invalid_inventory_quantity_fails(quantity: int) -> None:
    with pytest.raises(InvalidInventoryQuantityError):
        run(CommerceSandbox().restore_inventory("SKU-HEADPHONES-001", quantity))


def test_unknown_inventory_item_raises_typed_error() -> None:
    with pytest.raises(InventoryItemNotFoundError, match="SKU-404"):
        run(CommerceSandbox().restore_inventory("SKU-404", 1))


def test_duplicate_notifications_without_idempotency_are_observable() -> None:
    sandbox = CommerceSandbox()

    first = run(sandbox.send_confirmation("ORD-1001", "Order cancelled."))
    second = run(sandbox.send_confirmation("ORD-1001", "Order cancelled."))

    assert first.notification_id == "NOTIF-0001"
    assert second.notification_id == "NOTIF-0002"
    assert len(sandbox.snapshot().notifications) == 2


def test_notification_with_same_idempotency_key_returns_original() -> None:
    sandbox = CommerceSandbox()

    first = run(
        sandbox.send_confirmation(
            "ORD-1001",
            "Order cancelled.",
            idempotency_key="confirmation-ORD-1001",
        )
    )
    second = run(
        sandbox.send_confirmation(
            "ORD-1001",
            "Order cancelled.",
            idempotency_key="confirmation-ORD-1001",
        )
    )

    assert second == first
    assert len(sandbox.snapshot().notifications) == 1


def test_notification_idempotency_key_conflict_is_explicit() -> None:
    sandbox = CommerceSandbox()
    run(
        sandbox.send_confirmation(
            "ORD-1001",
            "Order cancelled.",
            idempotency_key="confirmation-key",
        )
    )

    with pytest.raises(IdempotencyConflictError, match="different request"):
        run(
            sandbox.send_confirmation(
                "ORD-1001",
                "Different message.",
                idempotency_key="confirmation-key",
            )
        )


def test_identifiers_restart_deterministically_after_reset() -> None:
    sandbox = CommerceSandbox()
    first_refund = run(sandbox.refund_payment("PAY-1001", Decimal("1.00")))
    first_notification = run(sandbox.send_confirmation("ORD-1001", "First notification."))

    sandbox.reset()

    reset_refund = run(sandbox.refund_payment("PAY-1001", Decimal("1.00")))
    reset_notification = run(sandbox.send_confirmation("ORD-1001", "First notification."))

    assert first_refund.refund_id == reset_refund.refund_id == "REF-0001"
    assert first_notification.notification_id == reset_notification.notification_id == "NOTIF-0001"


def test_money_uses_exact_decimal_arithmetic_and_rejects_float_refunds() -> None:
    sandbox = CommerceSandbox()
    initial = sandbox.snapshot()

    assert isinstance(initial.orders[0].total, Decimal)
    assert isinstance(initial.orders[0].items[0].unit_price, Decimal)
    assert initial.orders[0].items[0].line_total == Decimal("79.99")
    assert initial.orders[0].total == Decimal("79.99")

    with pytest.raises(InvalidRefundAmountError):
        run(sandbox.refund_payment("PAY-1001", 79.99))  # type: ignore[arg-type]


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("1.001")])
def test_invalid_refund_amount_fails(amount: Decimal) -> None:
    with pytest.raises(InvalidRefundAmountError):
        run(CommerceSandbox().refund_payment("PAY-1001", amount))
