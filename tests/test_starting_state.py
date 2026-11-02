"""D3 regression tests: the starting state must be verified against an independent declaration.

The defect (Milestone 1 closeout, M1-D3): ``COMMERCE_SCENARIO.initial_state`` was computed by
resetting the sandbox, and the runner then checked the sandbox's reset state against it. A check
of X against X cannot fail, so a change to the fixture would silently change what every
experiment tests. Separately, the runner compared only the scenario id and version of an
experiment's own declared scenario, so a spec file declaring a different starting state ran
anyway.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import Iterator
from decimal import Decimal
from importlib import resources

import pytest

import commerce_demo.scenario as scenario_module
from commerce_demo.agents import reconciling_agent
from commerce_demo.models import InventoryItem
from commerce_demo.repository import InMemoryCommerceStateRepository
from rift_experiment_runner import ExperimentConfigurationError, ExperimentRunner


class NoSleep:
    async def sleep(self, seconds: float) -> None:
        return None


def run(experiment, binding) -> None:
    runner = ExperimentRunner(sleeper=NoSleep())
    asyncio.run(runner.run(experiment, binding, reconciling_agent()))


@pytest.fixture
def drifted_fixture(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Simulate an edit to the sandbox's reset fixture: 9 headphones in stock becomes 8."""

    original_reset = InMemoryCommerceStateRepository.reset

    def drifted_reset(self: InMemoryCommerceStateRepository) -> None:
        original_reset(self)
        self.save_inventory_item(InventoryItem(sku="SKU-HEADPHONES-001", available_quantity=8))

    monkeypatch.setattr(InMemoryCommerceStateRepository, "reset", drifted_reset)
    # Reload so module-level declarations are rebuilt as they would be after a source edit.
    importlib.reload(scenario_module)
    try:
        yield
    finally:
        monkeypatch.undo()
        importlib.reload(scenario_module)


@pytest.mark.usefixtures("drifted_fixture")
def test_a_changed_sandbox_fixture_is_detected() -> None:
    experiment = scenario_module.commerce_experiment("drift", [])
    with pytest.raises(ExperimentConfigurationError, match="initial_state"):
        run(experiment, scenario_module.CommerceScenarioBinding())


def test_an_experiment_declaring_a_different_starting_state_is_rejected() -> None:
    declared = json.loads(json.dumps(scenario_module.COMMERCE_SCENARIO.initial_state))
    declared["inventory"][0]["available_quantity"] = 50
    experiment = scenario_module.commerce_experiment("other-start", []).model_copy(
        update={
            "scenario": scenario_module.COMMERCE_SCENARIO.model_copy(
                update={"initial_state": declared}
            )
        }
    )
    with pytest.raises(ExperimentConfigurationError, match="initial_state"):
        run(experiment, scenario_module.CommerceScenarioBinding())


def test_declared_starting_state_matches_the_documented_fixture() -> None:
    """Pin the declaration to docs/commerce-sandbox.md, not to the sandbox's own reset."""

    state = scenario_module.COMMERCE_SCENARIO.initial_state
    order = state["orders"][0]
    assert (order["order_id"], order["status"], Decimal(order["total"])) == (
        "ORD-1001",
        "confirmed",
        Decimal("79.99"),
    )
    payment = state["payments"][0]
    assert (payment["payment_id"], payment["status"], Decimal(payment["amount"])) == (
        "PAY-1001",
        "captured",
        Decimal("79.99"),
    )
    assert state["inventory"] == [{"sku": "SKU-HEADPHONES-001", "available_quantity": 9}]
    assert state["refunds"] == [] and state["notifications"] == []


def test_declared_starting_state_is_loaded_from_a_checked_in_fixture() -> None:
    fixture = resources.files("commerce_demo").joinpath("fixtures/initial_state.json")
    assert json.loads(fixture.read_text(encoding="utf-8")) == (
        scenario_module.COMMERCE_SCENARIO.initial_state
    )
