"""Agent-callable tool bindings for the commerce sandbox.

Handlers translate JSON-compatible arguments into typed sandbox calls and return JSON-compatible
results. Money crosses the boundary as a decimal string, never a float.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import JsonValue

from commerce_demo.errors import CommerceDomainError
from commerce_demo.sandbox import CommerceSandbox
from rift_core import ToolHandler, ToolSpec


class InvalidToolArgumentsError(CommerceDomainError):
    """Raised when an agent supplies missing or mistyped tool arguments."""


def _string(description: str) -> dict[str, JsonValue]:
    return {"type": "string", "description": description}


def _schema(properties: dict[str, JsonValue], required: list[JsonValue]) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_KEY = _string("Optional client-chosen key. Replaying a key returns the original result.")

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_order",
        description="Look up an order by ID.",
        parameters=_schema({"order_id": _string("Order ID")}, ["order_id"]),
    ),
    ToolSpec(
        name="cancel_order",
        description="Cancel a confirmed order. Cancelling an already-cancelled order is a no-op.",
        parameters=_schema({"order_id": _string("Order ID")}, ["order_id"]),
    ),
    ToolSpec(
        name="refund_payment",
        description=(
            "Refund a captured payment. Each call without an idempotency key refunds again."
        ),
        parameters=_schema(
            {
                "payment_id": _string("Payment ID"),
                "amount": _string("Decimal amount as a string, e.g. '79.99'"),
                "idempotency_key": _KEY,
            },
            ["payment_id", "amount"],
        ),
    ),
    ToolSpec(
        name="list_refunds",
        description="List refunds already issued for a payment.",
        parameters=_schema({"payment_id": _string("Payment ID")}, ["payment_id"]),
    ),
    ToolSpec(
        name="get_inventory",
        description="Read available inventory for a SKU.",
        parameters=_schema({"sku": _string("Stock-keeping unit")}, ["sku"]),
    ),
    ToolSpec(
        name="restore_inventory",
        description="Add units back to inventory. Not idempotent: every call adds again.",
        parameters=_schema(
            {"sku": _string("Stock-keeping unit"), "quantity": {"type": "integer", "minimum": 1}},
            ["sku", "quantity"],
        ),
    ),
    ToolSpec(
        name="send_confirmation",
        description="Send the customer a cancellation confirmation.",
        parameters=_schema(
            {
                "order_id": _string("Order ID"),
                "message": _string("Message body"),
                "idempotency_key": _KEY,
            },
            ["order_id", "message"],
        ),
    ),
)


def build_tool_handlers(sandbox: CommerceSandbox) -> dict[str, ToolHandler]:
    """Return handlers bound to one sandbox instance, keyed by tool name."""

    async def get_order(args: dict[str, JsonValue]) -> JsonValue:
        order = await sandbox.get_order(_required_str(args, "order_id"))
        return order.model_dump(mode="json")

    async def cancel_order(args: dict[str, JsonValue]) -> JsonValue:
        order = await sandbox.cancel_order(_required_str(args, "order_id"))
        return order.model_dump(mode="json")

    async def refund_payment(args: dict[str, JsonValue]) -> JsonValue:
        refund = await sandbox.refund_payment(
            _required_str(args, "payment_id"),
            _decimal(args, "amount"),
            idempotency_key=_optional_str(args, "idempotency_key"),
        )
        return refund.model_dump(mode="json")

    async def list_refunds(args: dict[str, JsonValue]) -> JsonValue:
        refunds = await sandbox.list_refunds(_required_str(args, "payment_id"))
        return [refund.model_dump(mode="json") for refund in refunds]

    async def get_inventory(args: dict[str, JsonValue]) -> JsonValue:
        item = await sandbox.get_inventory(_required_str(args, "sku"))
        return item.model_dump(mode="json")

    async def restore_inventory(args: dict[str, JsonValue]) -> JsonValue:
        quantity = args.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise InvalidToolArgumentsError("quantity must be an integer")
        item = await sandbox.restore_inventory(_required_str(args, "sku"), quantity)
        return item.model_dump(mode="json")

    async def send_confirmation(args: dict[str, JsonValue]) -> JsonValue:
        notification = await sandbox.send_confirmation(
            _required_str(args, "order_id"),
            _required_str(args, "message"),
            idempotency_key=_optional_str(args, "idempotency_key"),
        )
        return notification.model_dump(mode="json")

    handlers: dict[str, ToolHandler] = {
        "get_order": get_order,
        "cancel_order": cancel_order,
        "refund_payment": refund_payment,
        "list_refunds": list_refunds,
        "get_inventory": get_inventory,
        "restore_inventory": restore_inventory,
        "send_confirmation": send_confirmation,
    }
    return handlers


def _required_str(args: dict[str, JsonValue], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidToolArgumentsError(f"{name} must be a non-empty string")
    return value


def _optional_str(args: dict[str, JsonValue], name: str) -> str | None:
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidToolArgumentsError(f"{name} must be a string")
    return value


def _decimal(args: dict[str, JsonValue], name: str) -> Decimal:
    value = args.get(name)
    if not isinstance(value, str):
        raise InvalidToolArgumentsError(f"{name} must be a decimal string such as '79.99'")
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise InvalidToolArgumentsError(f"{name} is not a decimal: {value!r}") from error
