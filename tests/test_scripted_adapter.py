import asyncio
from collections import deque

from pydantic import JsonValue

from rift_agent_adapters import Reconciliation, RetryPolicy, ScriptedAgentAdapter, ScriptStep
from rift_core import AgentStatus, AgentTask, ToolCallOutcome, ToolErrorKind, ToolSpec

TASK = AgentTask(scenario_id="test", instruction="do it")
TIMEOUT = ToolCallOutcome(
    tool_name="x", ok=False, error_kind=ToolErrorKind.TIMEOUT, error_message="timed out"
)


def ok(response: JsonValue = None) -> ToolCallOutcome:
    return ToolCallOutcome(tool_name="x", ok=True, response=response)


class FakeGateway:
    """Returns queued outcomes per tool; defaults to success."""

    def __init__(self, **queued: list[ToolCallOutcome]) -> None:
        self.queued = {name: deque(items) for name, items in queued.items()}
        self.calls: list[str] = []

    @property
    def tools(self) -> tuple[ToolSpec, ...]:
        return ()

    async def call(self, tool_name: str, arguments: dict[str, JsonValue]) -> ToolCallOutcome:
        self.calls.append(tool_name)
        queue = self.queued.get(tool_name)
        return queue.popleft() if queue else ok({"ok": True})


def run(adapter: ScriptedAgentAdapter, gateway: FakeGateway):
    return asyncio.run(adapter.run(TASK, gateway))


def test_retries_until_success() -> None:
    gateway = FakeGateway(a=[TIMEOUT, TIMEOUT])
    adapter = ScriptedAgentAdapter(
        name="t", steps=[ScriptStep("a", retry=RetryPolicy(max_attempts=3))]
    )
    output = run(adapter, gateway)
    assert output.status is AgentStatus.COMPLETED
    assert gateway.calls == ["a", "a", "a"]
    assert output.tool_calls == 3


def test_abort_stops_and_reports_failure_honestly() -> None:
    gateway = FakeGateway(a=[TIMEOUT])
    adapter = ScriptedAgentAdapter(name="t", steps=[ScriptStep("a"), ScriptStep("b")])
    output = run(adapter, gateway)
    assert output.status is AgentStatus.GAVE_UP
    assert gateway.calls == ["a"]
    assert output.metadata["failed_steps"] == ["1:a (timeout, retries exhausted)"]


def test_dishonest_agent_continues_and_claims_success() -> None:
    gateway = FakeGateway(a=[TIMEOUT])
    adapter = ScriptedAgentAdapter(
        name="t",
        steps=[ScriptStep("a"), ScriptStep("b")],
        on_step_failure="continue",
        honest_reporting=False,
    )
    output = run(adapter, gateway)
    assert output.status is AgentStatus.COMPLETED
    assert gateway.calls == ["a", "b"]


def test_non_retryable_error_kind_is_not_retried() -> None:
    error = ToolCallOutcome(
        tool_name="a", ok=False, error_kind=ToolErrorKind.TOOL_ERROR, error_message="bad"
    )
    gateway = FakeGateway(a=[error])
    adapter = ScriptedAgentAdapter(
        name="t", steps=[ScriptStep("a", retry=RetryPolicy(max_attempts=3))]
    )
    assert run(adapter, gateway).status is AgentStatus.GAVE_UP
    assert gateway.calls == ["a"]


def test_invalid_response_is_retried_only_when_policy_allows() -> None:
    def has_id(response: JsonValue) -> bool:
        return isinstance(response, dict) and "id" in response

    strict = ScriptedAgentAdapter(name="t", steps=[ScriptStep("a", validate_response=has_id)])
    assert run(strict, FakeGateway(a=[ok({"bad": 1})])).status is AgentStatus.GAVE_UP

    retrying = ScriptedAgentAdapter(
        name="t",
        steps=[
            ScriptStep(
                "a",
                validate_response=has_id,
                retry=RetryPolicy(max_attempts=2, retry_on_invalid_response=True),
            )
        ],
    )
    gateway = FakeGateway(a=[ok({"bad": 1}), ok({"id": 1})])
    assert run(retrying, gateway).status is AgentStatus.COMPLETED
    assert gateway.calls == ["a", "a"]


def test_reconciliation_skips_retry_when_effect_already_applied() -> None:
    gateway = FakeGateway(
        probe=[ok({"n": 1}), ok({"n": 2})],
        write=[TIMEOUT],
    )
    adapter = ScriptedAgentAdapter(
        name="t",
        steps=[
            ScriptStep(
                "write",
                retry=RetryPolicy(max_attempts=3),
                reconcile=Reconciliation("probe", {}, lambda before, now: now["n"] > before["n"]),
            )
        ],
    )
    output = run(adapter, gateway)
    assert output.status is AgentStatus.COMPLETED
    assert gateway.calls == ["probe", "write", "probe"]


def test_reconciliation_retries_when_effect_not_applied() -> None:
    gateway = FakeGateway(probe=[ok({"n": 1}), ok({"n": 1})], write=[TIMEOUT])
    adapter = ScriptedAgentAdapter(
        name="t",
        steps=[
            ScriptStep(
                "write",
                retry=RetryPolicy(max_attempts=3),
                reconcile=Reconciliation("probe", {}, lambda before, now: now["n"] > before["n"]),
            )
        ],
    )
    assert run(adapter, gateway).status is AgentStatus.COMPLETED
    assert gateway.calls == ["probe", "write", "probe", "write"]
