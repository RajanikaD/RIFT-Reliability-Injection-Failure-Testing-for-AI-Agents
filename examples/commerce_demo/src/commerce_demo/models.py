"""Immutable ecommerce entities and state snapshots."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt
from pydantic.functional_validators import model_validator
from pydantic.types import StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


class OrderStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    CAPTURED = "captured"
    REFUNDED = "refunded"


class RefundStatus(StrEnum):
    SUCCEEDED = "succeeded"


class NotificationType(StrEnum):
    CANCELLATION_CONFIRMATION = "cancellation_confirmation"


class CommerceModel(BaseModel):
    """Strict and immutable base model for synthetic commerce state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class OrderItem(CommerceModel):
    sku: NonEmptyStr
    quantity: PositiveInt
    unit_price: Money

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


class Order(CommerceModel):
    order_id: NonEmptyStr
    status: OrderStatus
    items: tuple[OrderItem, ...] = Field(min_length=1)
    total: Money

    @model_validator(mode="after")
    def total_matches_items(self) -> Self:
        calculated_total = sum(
            (item.line_total for item in self.items),
            start=Decimal("0.00"),
        )
        if calculated_total != self.total:
            raise ValueError("order total must equal the sum of its item totals")
        return self


class Payment(CommerceModel):
    payment_id: NonEmptyStr
    order_id: NonEmptyStr
    status: PaymentStatus
    amount: Money


class Refund(CommerceModel):
    refund_id: NonEmptyStr
    payment_id: NonEmptyStr
    status: RefundStatus
    amount: Money
    idempotency_key: NonEmptyStr | None = None


class InventoryItem(CommerceModel):
    sku: NonEmptyStr
    available_quantity: NonNegativeInt


class Notification(CommerceModel):
    notification_id: NonEmptyStr
    order_id: NonEmptyStr
    notification_type: NotificationType
    message: NonEmptyStr
    idempotency_key: NonEmptyStr | None = None


class CommerceSnapshot(CommerceModel):
    """Detached immutable view of all state needed by later invariant evaluation."""

    orders: tuple[Order, ...]
    payments: tuple[Payment, ...]
    refunds: tuple[Refund, ...]
    inventory: tuple[InventoryItem, ...]
    notifications: tuple[Notification, ...]
