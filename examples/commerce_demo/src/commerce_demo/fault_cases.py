"""Named, documented fault cases for the commerce scenario."""

from __future__ import annotations

from dataclasses import dataclass

from rift_core import FaultRule, FaultType


@dataclass(frozen=True, slots=True)
class FaultCase:
    name: str
    summary: str
    rules: tuple[FaultRule, ...]


def _rule(tool: str, fault: FaultType, number: int = 1, **options: object) -> FaultRule:
    return FaultRule.model_validate(
        {
            "fault_rule_id": f"{tool}-{fault.value}-{number}",
            "tool_name": tool,
            "invocation_number": number,
            "fault_type": fault,
            **options,
        }
    )


FAULT_CASES: dict[str, FaultCase] = {
    case.name: case
    for case in (
        FaultCase(
            "none",
            "No faults. Faulted run equals baseline; verdict is not_exercised by design.",
            (),
        ),
        FaultCase(
            "refund-timeout-after-commit",
            "First refund commits, but the caller sees a timeout (ambiguous outcome).",
            (_rule("refund_payment", FaultType.TIMEOUT_AFTER_COMMIT),),
        ),
        FaultCase(
            "refund-timeout-before-call",
            "First refund times out before reaching the payment system; nothing happened.",
            (_rule("refund_payment", FaultType.TIMEOUT_BEFORE_CALL),),
        ),
        FaultCase(
            "refund-rate-limited",
            "First refund is rejected with HTTP 429 semantics.",
            (
                _rule(
                    "refund_payment",
                    FaultType.RATE_LIMIT,
                    error_message="429 Too Many Requests",
                ),
            ),
        ),
        FaultCase(
            "refund-outage",
            "Every refund attempt fails (three consecutive dependency errors).",
            tuple(
                _rule(
                    "refund_payment",
                    FaultType.EXCEPTION,
                    number,
                    error_message="payment provider unavailable",
                )
                for number in (1, 2, 3)
            ),
        ),
        FaultCase(
            "refund-malformed-response",
            "First refund commits, but its response is unparseable.",
            (
                _rule(
                    "refund_payment",
                    FaultType.MALFORMED_RESPONSE,
                    replacement_response={"status": "???"},
                ),
            ),
        ),
        FaultCase(
            "refund-duplicate-request",
            "Transport delivers the first refund request twice (at-least-once delivery).",
            (_rule("refund_payment", FaultType.DUPLICATE_REQUEST),),
        ),
        FaultCase(
            "inventory-timeout-after-commit",
            "Inventory restore commits, but the caller sees a timeout. No idempotency key exists.",
            (_rule("restore_inventory", FaultType.TIMEOUT_AFTER_COMMIT),),
        ),
        FaultCase(
            "confirmation-timeout-after-commit",
            "Confirmation is sent, but the caller sees a timeout.",
            (_rule("send_confirmation", FaultType.TIMEOUT_AFTER_COMMIT),),
        ),
        FaultCase(
            "cancel-latency",
            "Order cancellation is slow (50 ms) but succeeds.",
            (_rule("cancel_order", FaultType.LATENCY, delay_ms=50),),
        ),
    )
}
