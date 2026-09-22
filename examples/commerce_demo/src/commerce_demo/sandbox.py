"""Async business operations for the deterministic synthetic commerce system."""

from decimal import Decimal

from commerce_demo.errors import (
    IdempotencyConflictError,
    InvalidIdempotencyKeyError,
    InvalidInventoryQuantityError,
    InvalidNotificationMessageError,
    InvalidRefundAmountError,
    InventoryItemNotFoundError,
    OrderNotFoundError,
    PaymentNotFoundError,
)
from commerce_demo.models import (
    CommerceSnapshot,
    InventoryItem,
    Notification,
    NotificationType,
    Order,
    OrderStatus,
    PaymentStatus,
    Refund,
    RefundStatus,
)
from commerce_demo.repository import (
    CommerceStateRepository,
    InMemoryCommerceStateRepository,
    NotificationIdempotencyRecord,
    RefundIdempotencyRecord,
)


class CommerceSandbox:
    """Deterministic in-memory ecommerce behavior exposed as async operations."""

    def __init__(self, repository: CommerceStateRepository | None = None) -> None:
        self._repository = repository or InMemoryCommerceStateRepository()

    def reset(self) -> None:
        self._repository.reset()

    def snapshot(self) -> CommerceSnapshot:
        return self._repository.snapshot()

    async def get_order(self, order_id: str) -> Order:
        order = self._repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError(f"order not found: {order_id}")
        return order

    async def cancel_order(self, order_id: str) -> Order:
        order = await self.get_order(order_id)
        if order.status is OrderStatus.CANCELLED:
            return order

        cancelled_order = order.model_copy(update={"status": OrderStatus.CANCELLED})
        self._repository.save_order(cancelled_order)
        return cancelled_order

    async def refund_payment(
        self,
        payment_id: str,
        amount: Decimal,
        idempotency_key: str | None = None,
    ) -> Refund:
        _validate_refund_amount(amount)
        idempotency_key = _normalize_idempotency_key(idempotency_key)

        if idempotency_key is not None:
            existing = self._repository.get_refund_idempotency(idempotency_key)
            if existing is not None:
                if existing.payment_id != payment_id or existing.amount != amount:
                    raise IdempotencyConflictError(
                        f"refund idempotency key reused with different request: {idempotency_key}"
                    )
                refund = self._repository.get_refund(existing.refund_id)
                if refund is None:
                    raise RuntimeError("refund idempotency index references missing state")
                return refund

        payment = self._repository.get_payment(payment_id)
        if payment is None:
            raise PaymentNotFoundError(f"payment not found: {payment_id}")

        refund = Refund(
            refund_id=self._repository.next_refund_id(),
            payment_id=payment_id,
            status=RefundStatus.SUCCEEDED,
            amount=amount,
            idempotency_key=idempotency_key,
        )
        self._repository.add_refund(refund)
        self._repository.save_payment(payment.model_copy(update={"status": PaymentStatus.REFUNDED}))

        if idempotency_key is not None:
            self._repository.save_refund_idempotency(
                idempotency_key,
                RefundIdempotencyRecord(
                    payment_id=payment_id,
                    amount=amount,
                    refund_id=refund.refund_id,
                ),
            )

        return refund

    async def restore_inventory(self, sku: str, quantity: int) -> InventoryItem:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise InvalidInventoryQuantityError(
                "inventory restoration quantity must be a positive integer"
            )

        item = self._repository.get_inventory_item(sku)
        if item is None:
            raise InventoryItemNotFoundError(f"inventory item not found: {sku}")

        updated_item = item.model_copy(
            update={"available_quantity": item.available_quantity + quantity}
        )
        self._repository.save_inventory_item(updated_item)
        return updated_item

    async def send_confirmation(
        self,
        order_id: str,
        message: str,
        idempotency_key: str | None = None,
    ) -> Notification:
        normalized_message = message.strip()
        if not normalized_message:
            raise InvalidNotificationMessageError("confirmation message must not be empty")
        idempotency_key = _normalize_idempotency_key(idempotency_key)

        if idempotency_key is not None:
            existing = self._repository.get_notification_idempotency(idempotency_key)
            if existing is not None:
                if existing.order_id != order_id or existing.message != normalized_message:
                    raise IdempotencyConflictError(
                        "notification idempotency key reused with different request: "
                        f"{idempotency_key}"
                    )
                notification = self._repository.get_notification(existing.notification_id)
                if notification is None:
                    raise RuntimeError("notification idempotency index references missing state")
                return notification

        await self.get_order(order_id)

        notification = Notification(
            notification_id=self._repository.next_notification_id(),
            order_id=order_id,
            notification_type=NotificationType.CANCELLATION_CONFIRMATION,
            message=normalized_message,
            idempotency_key=idempotency_key,
        )
        self._repository.add_notification(notification)

        if idempotency_key is not None:
            self._repository.save_notification_idempotency(
                idempotency_key,
                NotificationIdempotencyRecord(
                    order_id=order_id,
                    message=normalized_message,
                    notification_id=notification.notification_id,
                ),
            )

        return notification


def _validate_refund_amount(amount: object) -> None:
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
        raise InvalidRefundAmountError("refund amount must be a positive Decimal value")
    if amount.as_tuple().exponent < -2:
        raise InvalidRefundAmountError("refund amount cannot have more than two decimal places")


def _normalize_idempotency_key(idempotency_key: str | None) -> str | None:
    if idempotency_key is None:
        return None
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise InvalidIdempotencyKeyError("idempotency key must not be empty")
    return normalized_key
