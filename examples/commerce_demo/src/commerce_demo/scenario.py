"""Bind the commerce sandbox, tools and invariants into a runnable RIFT scenario."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from commerce_demo.invariants import commerce_cancellation_invariants
from commerce_demo.models import CommerceSnapshot
from commerce_demo.sandbox import CommerceSandbox
from commerce_demo.tools import TOOL_SPECS, build_tool_handlers
from rift_core import ExperimentSpec, FaultRule, ScenarioSpec, ToolHandler, ToolSpec
from rift_invariant_engine import Invariant

SCENARIO_ID = "commerce.cancel_order"
TASK = "Cancel order ORD-1001, refund the customer, restore inventory, and send confirmation."


class CommerceEnvironment:
    """One isolated commerce sandbox exposed through the runner's environment protocol."""

    def __init__(self) -> None:
        self._sandbox = CommerceSandbox()
        self._handlers = build_tool_handlers(self._sandbox)

    def reset(self) -> None:
        self._sandbox.reset()

    def snapshot(self) -> CommerceSnapshot:
        return self._sandbox.snapshot()

    def snapshot_json(self, state: CommerceSnapshot) -> dict[str, JsonValue]:
        return state.model_dump(mode="json")

    def tool_handlers(self) -> Mapping[str, ToolHandler]:
        return self._handlers

    def tool_specs(self) -> tuple[ToolSpec, ...]:
        return TOOL_SPECS


def _initial_state() -> dict[str, JsonValue]:
    environment = CommerceEnvironment()
    return environment.snapshot_json(environment.snapshot())


COMMERCE_SCENARIO = ScenarioSpec(
    scenario_id=SCENARIO_ID,
    name="Cancel and refund an ecommerce order",
    task=TASK,
    version=1,
    initial_state=_initial_state(),
    tool_names=tuple(spec.name for spec in TOOL_SPECS),
    invariant_ids=tuple(invariant.name for invariant in commerce_cancellation_invariants()),
)


class CommerceScenarioBinding:
    """The ``ScenarioBinding`` for :data:`COMMERCE_SCENARIO`."""

    @property
    def spec(self) -> ScenarioSpec:
        return COMMERCE_SCENARIO

    def create_environment(self) -> CommerceEnvironment:
        return CommerceEnvironment()

    def invariants(self) -> Sequence[Invariant[CommerceSnapshot]]:
        return commerce_cancellation_invariants()


def commerce_experiment(
    experiment_id: str,
    fault_rules: Sequence[FaultRule],
    *,
    seed: int = 0,
    description: str | None = None,
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        name=experiment_id,
        scenario=COMMERCE_SCENARIO,
        seed=seed,
        fault_rules=tuple(fault_rules),
        description=description,
    )
