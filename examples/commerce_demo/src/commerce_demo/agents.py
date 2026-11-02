"""Scripted agent profiles that embody common recovery strategies.

Each profile performs the same four business actions. They differ only in how they react to
failures, which is exactly the variable a reliability experiment should isolate.

| Profile       | Retries | Idempotency keys | Validates responses | Reconciles state | Honest |
| ------------- | ------- | ---------------- | ------------------- | ---------------- | ------ |
| naive         | no      | no               | no                  | no               | no     |
| retrying      | yes     | no               | yes                 | no               | yes    |
| idempotent    | yes     | yes              | yes                 | no               | yes    |
| reconciling   | yes     | yes              | yes                 | inventory        | yes    |
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import JsonValue

from commerce_demo.invariants import EXPECTED_REFUND_AMOUNT, ORDER_ID, PAYMENT_ID, SKU
from rift_agent_adapters import Reconciliation, RetryPolicy, ScriptedAgentAdapter, ScriptStep
from rift_core import ToolErrorKind

CONFIRMATION_MESSAGE = "Your order ORD-1001 has been cancelled and refunded."
SUCCESS_MESSAGE = "Order ORD-1001 was cancelled, refunded, restocked, and the customer notified."
FAILURE_MESSAGE = "I could not fully process the cancellation of ORD-1001."

_RETRY = RetryPolicy(
    max_attempts=3,
    retry_on=frozenset(
        {ToolErrorKind.TIMEOUT, ToolErrorKind.RATE_LIMITED, ToolErrorKind.TOOL_ERROR}
    ),
    retry_on_invalid_response=True,
)


def _has_keys(*keys: str) -> Callable[[JsonValue], bool]:
    def validate(response: JsonValue) -> bool:
        return isinstance(response, dict) and all(key in response for key in keys)

    return validate


def _inventory_increased(before: JsonValue, now: JsonValue) -> bool:
    if not isinstance(before, dict) or not isinstance(now, dict):
        return False
    previous, current = before.get("available_quantity"), now.get("available_quantity")
    return isinstance(previous, int) and isinstance(current, int) and current > previous


def _steps(
    *, retry: RetryPolicy, keys: bool, validate: bool, reconcile_inventory: bool
) -> list[ScriptStep]:
    refund_args: dict[str, JsonValue] = {
        "payment_id": PAYMENT_ID,
        "amount": str(EXPECTED_REFUND_AMOUNT),
    }
    confirm_args: dict[str, JsonValue] = {"order_id": ORDER_ID, "message": CONFIRMATION_MESSAGE}
    if keys:
        refund_args["idempotency_key"] = f"refund-{ORDER_ID}"
        confirm_args["idempotency_key"] = f"confirm-{ORDER_ID}"
    return [
        ScriptStep(
            "cancel_order",
            {"order_id": ORDER_ID},
            retry=retry,
            validate_response=_has_keys("order_id", "status") if validate else None,
        ),
        ScriptStep(
            "refund_payment",
            refund_args,
            retry=retry,
            validate_response=_has_keys("refund_id", "amount") if validate else None,
        ),
        ScriptStep(
            "restore_inventory",
            {"sku": SKU, "quantity": 1},
            retry=retry,
            validate_response=_has_keys("sku", "available_quantity") if validate else None,
            reconcile=(
                Reconciliation("get_inventory", {"sku": SKU}, _inventory_increased)
                if reconcile_inventory
                else None
            ),
        ),
        ScriptStep(
            "send_confirmation",
            confirm_args,
            retry=retry,
            validate_response=_has_keys("notification_id") if validate else None,
        ),
    ]


def naive_agent() -> ScriptedAgentAdapter:
    """Calls each tool once, ignores errors, and always reports success."""

    return ScriptedAgentAdapter(
        name="naive",
        steps=_steps(retry=RetryPolicy(), keys=False, validate=False, reconcile_inventory=False),
        on_step_failure="continue",
        honest_reporting=False,
        success_message=SUCCESS_MESSAGE,
        failure_message=FAILURE_MESSAGE,
    )


def retrying_agent() -> ScriptedAgentAdapter:
    """Retries failures up to three times, without idempotency keys."""

    return ScriptedAgentAdapter(
        name="retrying",
        steps=_steps(retry=_RETRY, keys=False, validate=True, reconcile_inventory=False),
        success_message=SUCCESS_MESSAGE,
        failure_message=FAILURE_MESSAGE,
    )


def idempotent_agent() -> ScriptedAgentAdapter:
    """Retries with stable idempotency keys where the API supports them."""

    return ScriptedAgentAdapter(
        name="idempotent",
        steps=_steps(retry=_RETRY, keys=True, validate=True, reconcile_inventory=False),
        success_message=SUCCESS_MESSAGE,
        failure_message=FAILURE_MESSAGE,
    )


def reconciling_agent() -> ScriptedAgentAdapter:
    """Uses idempotency keys and, for non-idempotent inventory, checks state before retrying."""

    return ScriptedAgentAdapter(
        name="reconciling",
        steps=_steps(retry=_RETRY, keys=True, validate=True, reconcile_inventory=True),
        success_message=SUCCESS_MESSAGE,
        failure_message=FAILURE_MESSAGE,
    )


AGENT_PROFILES: dict[str, Callable[[], ScriptedAgentAdapter]] = {
    "naive": naive_agent,
    "retrying": retrying_agent,
    "idempotent": idempotent_agent,
    "reconciling": reconciling_agent,
}
