"""State repository contract and deterministic in-memory implementation."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from commerce_demo.models import (
    CommerceSnapshot,
    InventoryItem,
    Notification,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentStatus,
    Refund,
)


@dataclass(frozen=True, slots=True)
class RefundIdempotencyRecord:
    payment_id: str
    amount: Decimal
    refund_id: str


@dataclass(frozen=True, slots=True)
class NotificationIdempotencyRecord:
    order_id: str
    message: str
    notification_id: str


class CommerceStateRepository(Protocol):
    """Storage boundary required by `CommerceSandbox`."""

    def reset(self) -> None: ...

    def snapshot(self) -> CommerceSnapshot: ...

    def get_order(self, order_id: str) -> Order | None: ...

    def save_order(self, order: Order) -> None: ...

    def get_payment(self, payment_id: str) -> Payment | None: ...

    def save_payment(self, payment: Payment) -> None: ...

    def get_inventory_item(self, sku: str) -> InventoryItem | None: ...

    def save_inventory_item(self, item: InventoryItem) -> None: ...

    def get_refund(self, refund_id: str) -> Refund | None: ...

    def add_refund(self, refund: Refund) -> None: ...

    def get_notification(self, notification_id: str) -> Notification | None: ...

    def add_notification(self, notification: Notification) -> None: ...

    def next_refund_id(self) -> str: ...

    def next_notification_id(self) -> str: ...

    def get_refund_idempotency(self, key: str) -> RefundIdempotencyRecord | None: ...

    def save_refund_idempotency(self, key: str, record: RefundIdempotencyRecord) -> None: ...

    def get_notification_idempotency(self, key: str) -> NotificationIdempotencyRecord | None: ...

    def save_notification_idempotency(
        self, key: str, record: NotificationIdempotencyRecord
    ) -> None: ...


class InMemoryCommerceStateRepository:
    """Deterministic local state store with resettable sequences."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        item = OrderItem(
            sku="SKU-HEADPHONES-001",
            quantity=1,
            unit_price=Decimal("79.99"),
        )
        order = Order(
            order_id="ORD-1001",
            status=OrderStatus.CONFIRMED,
            items=(item,),
            total=Decimal("79.99"),
        )
        payment = Payment(
            payment_id="PAY-1001",
            order_id=order.order_id,
            status=PaymentStatus.CAPTURED,
            amount=Decimal("79.99"),
        )
        inventory_item = InventoryItem(
            sku=item.sku,
            available_quantity=9,
        )

        self._orders = {order.order_id: order}
        self._payments = {payment.payment_id: payment}
        self._refunds: dict[str, Refund] = {}
        self._inventory = {inventory_item.sku: inventory_item}
        self._notifications: dict[str, Notification] = {}
        self._refund_idempotency: dict[str, RefundIdempotencyRecord] = {}
        self._notification_idempotency: dict[str, NotificationIdempotencyRecord] = {}
        self._next_refund_number = 1
        self._next_notification_number = 1

    def snapshot(self) -> CommerceSnapshot:
        return CommerceSnapshot(
            orders=tuple(self._orders[key] for key in sorted(self._orders)),
            payments=tuple(self._payments[key] for key in sorted(self._payments)),
            refunds=tuple(self._refunds[key] for key in sorted(self._refunds)),
            inventory=tuple(self._inventory[key] for key in sorted(self._inventory)),
            notifications=tuple(self._notifications[key] for key in sorted(self._notifications)),
        )

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def save_order(self, order: Order) -> None:
        self._orders[order.order_id] = order

    def get_payment(self, payment_id: str) -> Payment | None:
        return self._payments.get(payment_id)

    def save_payment(self, payment: Payment) -> None:
        self._payments[payment.payment_id] = payment

    def get_inventory_item(self, sku: str) -> InventoryItem | None:
        return self._inventory.get(sku)

    def save_inventory_item(self, item: InventoryItem) -> None:
        self._inventory[item.sku] = item

    def get_refund(self, refund_id: str) -> Refund | None:
        return self._refunds.get(refund_id)

    def add_refund(self, refund: Refund) -> None:
        self._refunds[refund.refund_id] = refund

    def get_notification(self, notification_id: str) -> Notification | None:
        return self._notifications.get(notification_id)

    def add_notification(self, notification: Notification) -> None:
        self._notifications[notification.notification_id] = notification

    def next_refund_id(self) -> str:
        refund_id = f"REF-{self._next_refund_number:04d}"
        self._next_refund_number += 1
        return refund_id

    def next_notification_id(self) -> str:
        notification_id = f"NOTIF-{self._next_notification_number:04d}"
        self._next_notification_number += 1
        return notification_id

    def get_refund_idempotency(self, key: str) -> RefundIdempotencyRecord | None:
        return self._refund_idempotency.get(key)

    def save_refund_idempotency(self, key: str, record: RefundIdempotencyRecord) -> None:
        self._refund_idempotency[key] = record

    def get_notification_idempotency(self, key: str) -> NotificationIdempotencyRecord | None:
        return self._notification_idempotency.get(key)

    def save_notification_idempotency(
        self, key: str, record: NotificationIdempotencyRecord
    ) -> None:
        self._notification_idempotency[key] = record
