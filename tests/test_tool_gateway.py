import asyncio

from pydantic import JsonValue

from rift_core import ExecutionContext, FaultRule, FaultType, RunMode, ToolErrorKind, ToolSpec
from rift_experiment_runner import ExecutorToolGateway
from rift_fault_engine import FaultInjectingToolExecutor, InMemoryInvocationRecorder

CONTEXT = ExecutionContext(
    experiment_id="gw", run_id="gw:faulted", seed=0, run_mode=RunMode.FAULTED
)


class Counter:
    def __init__(self) -> None:
        self.calls = 0

    async def handler(self, arguments: dict[str, JsonValue]) -> JsonValue:
        self.calls += 1
        if arguments.get("fail"):
            raise LookupError("record missing")
        return {"count": self.calls}


def gateway(
    *rules: FaultRule, budget: int = 10
) -> tuple[ExecutorToolGateway, Counter, InMemoryInvocationRecorder]:
    counter = Counter()
    recorder = InMemoryInvocationRecorder()
    executor = FaultInjectingToolExecutor(rules, recorder=recorder)
    return (
        ExecutorToolGateway(
            executor=executor,
            handlers={"write": counter.handler},
            specs=(ToolSpec(name="write", description="Write a record."),),
            execution_context=CONTEXT,
            max_tool_calls=budget,
        ),
        counter,
        recorder,
    )


def rule(fault_type: FaultType, **options: object) -> FaultRule:
    return FaultRule.model_validate(
        {
            "fault_rule_id": "r1",
            "tool_name": "write",
            "invocation_number": 1,
            "fault_type": fault_type,
            **options,
        }
    )


def test_both_timeout_kinds_are_indistinguishable_to_the_agent() -> None:
    before, before_counter, _ = gateway(rule(FaultType.TIMEOUT_BEFORE_CALL, error_message="a"))
    after, after_counter, _ = gateway(rule(FaultType.TIMEOUT_AFTER_COMMIT, error_message="b"))

    seen_before = asyncio.run(before.call("write", {}))
    seen_after = asyncio.run(after.call("write", {}))

    assert seen_before == seen_after
    assert seen_before.error_kind is ToolErrorKind.TIMEOUT
    # ...while the actual world differs.
    assert (before_counter.calls, after_counter.calls) == (0, 1)


def test_rate_limit_is_retryable() -> None:
    gw, counter, _ = gateway(rule(FaultType.RATE_LIMIT, error_message="429 Too Many Requests"))
    outcome = asyncio.run(gw.call("write", {}))
    assert outcome.error_kind is ToolErrorKind.RATE_LIMITED
    assert outcome.retryable is True
    assert counter.calls == 0


def test_injected_exception_looks_like_a_dependency_error() -> None:
    gw, _, _ = gateway(rule(FaultType.EXCEPTION, error_message="provider down"))
    outcome = asyncio.run(gw.call("write", {}))
    assert outcome.error_kind is ToolErrorKind.TOOL_ERROR
    assert outcome.error_message == "DependencyError: provider down"
    assert "Injected" not in outcome.error_message


def test_genuine_tool_error_is_returned_not_raised_and_recorded() -> None:
    gw, _, recorder = gateway()
    outcome = asyncio.run(gw.call("write", {"fail": True}))
    assert outcome.ok is False
    assert outcome.error_message == "LookupError: record missing"
    assert recorder.records[0].underlying_error == "LookupError: record missing"


def test_unknown_tool_and_budget_do_not_execute_or_record() -> None:
    gw, counter, recorder = gateway(budget=1)
    unknown = asyncio.run(gw.call("delete_everything", {}))
    exhausted = asyncio.run(gw.call("write", {}))
    assert unknown.error_kind is ToolErrorKind.UNKNOWN_TOOL
    assert exhausted.error_kind is ToolErrorKind.CALL_BUDGET_EXHAUSTED
    assert counter.calls == 0
    assert recorder.records == ()


def test_success_exposes_only_the_caller_visible_result() -> None:
    gw, _, _ = gateway(rule(FaultType.MALFORMED_RESPONSE, replacement_response={"x": None}))
    outcome = asyncio.run(gw.call("write", {}))
    assert outcome.ok is True
    assert outcome.response == {"x": None}
