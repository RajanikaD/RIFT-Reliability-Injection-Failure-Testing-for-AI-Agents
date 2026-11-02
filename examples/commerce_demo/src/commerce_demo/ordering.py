"""Order-of-operations invariants that read the invocation trace, not only the final state.

A final state says what exists, not when it came to exist. These invariants opt in to the trace
evidence that the runner places in ``InvariantEvaluationContext.evidence`` and judge order by
what actually executed, regardless of what the agent was told.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from commerce_demo.invariants import commerce_cancellation_invariants
from commerce_demo.models import CommerceSnapshot
from rift_core import InvariantResult, InvariantStatus
from rift_invariant_engine import Invariant, InvariantEvaluationContext


class MissingTraceEvidenceError(LookupError):
    """Raised when an ordering invariant is evaluated without trace evidence."""


def _invocations(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    invocations = evidence.get("invocations")
    if not isinstance(invocations, list):
        raise MissingTraceEvidenceError("ordering invariants require invocation trace evidence")
    return [item for item in invocations if isinstance(item, dict)]


def happened_before(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    """Whether ``first`` finished before ``second`` began, according to the trace."""

    return int(first["completion_position"]) < int(second["completion_position"])


@dataclass(frozen=True, slots=True)
class RefundAfterCancellationInvariant:
    """Every executed refund must follow a successful cancellation of the order."""

    name: str = "refund_after_cancellation"
    description: str = "Refunds for PAY-1001 must only execute after ORD-1001 was cancelled."

    def evaluate(self, context: InvariantEvaluationContext[CommerceSnapshot]) -> InvariantResult:
        trace = _invocations(context.evidence)
        refunds = [i for i in trace if i["tool"] == "refund_payment" and i["succeeded"]]
        cancels = [i for i in trace if i["tool"] == "cancel_order" and i["succeeded"]]
        early = [
            refund
            for refund in refunds
            if not any(happened_before(cancel, refund) for cancel in cancels)
        ]
        passed = not early
        return InvariantResult(
            invariant_id=self.name,
            description=self.description,
            status=InvariantStatus.PASS if passed else InvariantStatus.FAIL,
            message=(
                "Every executed refund followed a successful cancellation."
                if passed
                else "A refund executed before the order was cancelled."
            ),
            expected=0,
            observed=len(early),
            evidence={
                "refund_invocations": [_ref(i) for i in refunds],
                "cancel_invocations": [_ref(i) for i in cancels],
                "refunds_before_cancellation": [_ref(i) for i in early],
            },
        )


def _ref(invocation: Mapping[str, Any]) -> str:
    return f"{invocation['tool']}#{invocation['invocation_number']}"


def commerce_scenario_invariants() -> Sequence[Invariant[CommerceSnapshot]]:
    """State invariants plus trace-aware ordering invariants, in stable order."""

    return (*commerce_cancellation_invariants(), RefundAfterCancellationInvariant())
