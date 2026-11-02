"""Regenerate the Milestone 2 sample reports in docs/samples/m2/.

Usage: uv run python scripts/generate_m2_samples.py
Timestamps inside the JSON reports differ on every run; everything else is reproducible.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import JsonValue

from commerce_demo.agents import AGENT_PROFILES
from commerce_demo.fault_cases import FAULT_CASES
from commerce_demo.scenario import CommerceScenarioBinding, commerce_experiment
from rift_agent_adapters import ScriptedAgentAdapter, ScriptStep
from rift_core import AgentRunOutput, AgentStatus, AgentTask, FaultRule, FaultType, ToolGateway
from rift_experiment_runner import ExperimentReport, ExperimentRunner, render_text

OUT = Path(__file__).parents[1] / "docs" / "samples" / "m2"


class TickSleeper:
    """Latency measured in event-loop ticks so concurrency samples are deterministic."""

    async def sleep(self, seconds: float) -> None:
        for _ in range(round(seconds * 1000)):
            await asyncio.sleep(0)


class ConcurrentAgent:
    name = "concurrent"
    version = "sample"

    async def run(self, task: AgentTask, gateway: ToolGateway) -> AgentRunOutput:
        refund: dict[str, JsonValue] = {
            "payment_id": "PAY-1001",
            "amount": "79.99",
            "idempotency_key": "refund-ORD-1001",
        }
        await asyncio.gather(
            gateway.call("cancel_order", {"order_id": "ORD-1001"}),
            gateway.call("refund_payment", refund),
        )
        await gateway.call("restore_inventory", {"sku": "SKU-HEADPHONES-001", "quantity": 1})
        await gateway.call("send_confirmation", {"order_id": "ORD-1001", "message": "Done."})
        return AgentRunOutput(status=AgentStatus.COMPLETED, final_message="All done.")


def refund_first_agent() -> ScriptedAgentAdapter:
    return ScriptedAgentAdapter(
        name="refund-first",
        steps=[
            ScriptStep("refund_payment", {"payment_id": "PAY-1001", "amount": "79.99"}),
            ScriptStep("send_confirmation", {"order_id": "ORD-1001", "message": "Done."}),
            ScriptStep("restore_inventory", {"sku": "SKU-HEADPHONES-001", "quantity": 1}),
            ScriptStep("cancel_order", {"order_id": "ORD-1001"}),
        ],
        success_message="Order cancelled and refunded.",
    )


def latency(tool: str, ticks: int) -> FaultRule:
    return FaultRule(
        fault_rule_id=f"{tool}-latency",
        tool_name=tool,
        invocation_number=1,
        fault_type=FaultType.LATENCY,
        delay_ms=ticks,
    )


def write(name: str, report: ExperimentReport, *, with_json: bool = False) -> None:
    (OUT / f"{name}.txt").write_text(render_text(report) + "\n", encoding="utf-8")
    if with_json:
        (OUT / f"{name}.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    binding = CommerceScenarioBinding()
    runner = ExperimentRunner(sleeper=TickSleeper())

    case = FAULT_CASES["refund-timeout-after-commit"]
    unsafe = commerce_experiment("retrying--refund-timeout-after-commit", case.rules)
    write(
        "retrying--refund-timeout-after-commit",
        asyncio.run(runner.run(unsafe, binding, AGENT_PROFILES["retrying"]())),
        with_json=True,
    )

    wrong_order = commerce_experiment("refund-first--no-faults", [])
    write(
        "refund-first--ordering-violation",
        asyncio.run(runner.run(wrong_order, binding, refund_first_agent())),
    )

    overlap = commerce_experiment(
        "concurrent--overlapping-cancel-and-refund",
        [latency("cancel_order", 1), latency("refund_payment", 3)],
    )
    write(
        "concurrent--overlapping-cancel-and-refund",
        asyncio.run(runner.run(overlap, binding, ConcurrentAgent())),
    )


if __name__ == "__main__":
    main()
