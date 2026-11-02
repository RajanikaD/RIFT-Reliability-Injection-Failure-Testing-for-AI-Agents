"""Outcome invariants for the deterministic order-cancellation scenario."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from commerce_demo.models import CommerceSnapshot, Notification, NotificationType, Refund
from rift_core import InvariantResult, InvariantStatus
from rift_invariant_engine import (
    CountEqualsInvariant,
    FieldEqualsInvariant,
    Invariant,
    InvariantEvaluationContext,
    NumericEqualsInvariant,
)

ORDER_ID = "ORD-1001"
PAYMENT_ID = "PAY-1001"
SKU = "SKU-HEADPHONES-001"
EXPECTED_REFUND_AMOUNT = Decimal("79.99")


@dataclass(frozen=True, slots=True)
class RefundAmountCorrectInvariant:
    """Require one refund and an exact total, so duplicates cannot appear correct."""

    name: str = "refund_amount_correct"
    description: str = (
        "PAY-1001 must have exactly one refund totaling the intended amount of 79.99."
    )

    def evaluate(self, context: InvariantEvaluationContext[CommerceSnapshot]) -> InvariantResult:
        refunds = tuple(
            refund for refund in context.after_state.refunds if refund.payment_id == PAYMENT_ID
        )
        total = sum((refund.amount for refund in refunds), start=Decimal("0.00"))
        passed = len(refunds) == 1 and total == EXPECTED_REFUND_AMOUNT
        return InvariantResult(
            invariant_id=self.name,
            description=self.description,
            status=InvariantStatus.PASS if passed else InvariantStatus.FAIL,
            message=(
                "Refund count and amount are correct."
                if passed
                else "Refund count or total amount is incorrect."
            ),
            expected=str(EXPECTED_REFUND_AMOUNT),
            observed=str(total),
            evidence={
                "payment_id": PAYMENT_ID,
                "refund_count": len(refunds),
                "refund_ids": [refund.refund_id for refund in refunds],
            },
        )


def commerce_cancellation_invariants() -> tuple[Invariant[CommerceSnapshot], ...]:
    """Return the scenario's invariant set in stable presentation order."""

    return (
        FieldEqualsInvariant(
            name="order_cancelled",
            description="ORD-1001 must be in the CANCELLED state.",
            selector=lambda context: _order_status(context.after_state, ORDER_ID),
            expected="CANCELLED",
            evidence_selector=lambda _context: {"order_id": ORDER_ID},
        ),
        CountEqualsInvariant(
            name="exactly_one_refund",
            description="PAY-1001 must have exactly one refund record.",
            selector=lambda context: _refunds_for_payment(context.after_state, PAYMENT_ID),
            expected=1,
            evidence_selector=lambda context: {
                "payment_id": PAYMENT_ID,
                "refund_ids": [
                    refund.refund_id
                    for refund in _refunds_for_payment(context.after_state, PAYMENT_ID)
                ],
            },
        ),
        RefundAmountCorrectInvariant(),
        NumericEqualsInvariant(
            name="inventory_restored",
            description=("SKU-HEADPHONES-001 available inventory must increase by exactly one."),
            selector=lambda context: (
                _inventory_quantity(context.after_state, SKU)
                - _inventory_quantity(context.before_state, SKU)
            ),
            expected=1,
            evidence_selector=lambda context: {
                "sku": SKU,
                "before_quantity": _inventory_quantity(context.before_state, SKU),
                "after_quantity": _inventory_quantity(context.after_state, SKU),
            },
        ),
        CountEqualsInvariant(
            name="single_confirmation",
            description="ORD-1001 must have exactly one cancellation confirmation.",
            selector=lambda context: _confirmations_for_order(context.after_state, ORDER_ID),
            expected=1,
            evidence_selector=lambda context: {
                "order_id": ORDER_ID,
                "notification_ids": [
                    notification.notification_id
                    for notification in _confirmations_for_order(context.after_state, ORDER_ID)
                ],
            },
        ),
    )


def _order_status(snapshot: CommerceSnapshot, order_id: str) -> str:
    order = next((item for item in snapshot.orders if item.order_id == order_id), None)
    if order is None:
        raise LookupError(f"order not found in snapshot: {order_id}")
    return order.status.name


def _refunds_for_payment(snapshot: CommerceSnapshot, payment_id: str) -> tuple[Refund, ...]:
    return tuple(refund for refund in snapshot.refunds if refund.payment_id == payment_id)


def _inventory_quantity(snapshot: CommerceSnapshot, sku: str) -> int:
    item = next((item for item in snapshot.inventory if item.sku == sku), None)
    if item is None:
        raise LookupError(f"inventory item not found in snapshot: {sku}")
    return item.available_quantity


def _confirmations_for_order(snapshot: CommerceSnapshot, order_id: str) -> tuple[Notification, ...]:
    return tuple(
        notification
        for notification in snapshot.notifications
        if notification.order_id == order_id
        and notification.notification_type is NotificationType.CANCELLATION_CONFIRMATION
    )
