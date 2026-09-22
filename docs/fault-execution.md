# Fault execution

## Scope

The `rift_fault_engine` package implements RIFT's framework-neutral boundary around asynchronous tool operations. It numbers calls, deterministically selects configured `FaultRule` objects, controls whether the operation executes, and records immutable `ToolInvocation` evidence.

It does not orchestrate experiments, bind agent frameworks, implement scenario tools, evaluate invariants, or persist records.

## Execution contract

Both `DirectToolExecutor` and `FaultInjectingToolExecutor` accept:

- A tool name.
- JSON-compatible arguments for evidence capture.
- A zero-argument async operation. The closure is responsible for binding its typed arguments.
- An `ExecutionContext` identifying the experiment, run, seed, and run mode.

Successful execution returns a typed `ToolExecution` containing the caller-visible result and its `ToolInvocation`. Injected errors carry the invocation record on the exception. Every executor also writes completed records to an `InvocationRecorder`; the default in-memory recorder exposes them through `invocations` and `invocations_for(context)`. This gives RIFT access to evidence even when an underlying, non-RIFT exception is re-raised unchanged.

## Interception lifecycle

1. Increment the counter for `(experiment_id, run_id, tool_name)` and assign a one-based invocation number.
2. Capture wall-clock and monotonic start times.
3. In a faulted run, find the rule matching the tool name and invocation number. Baseline runs cannot match rules.
4. Apply at most one behavior:
   - Execute normally.
   - Produce a before-call failure without invoking the operation.
   - Delay and then execute.
   - Execute successfully and alter the caller-visible outcome.
5. Capture completion time, duration, actual operation evidence, and caller-visible evidence.
6. Finalize and record a `ToolInvocation`.
7. Return `ToolExecution` or raise the appropriate exception.

Rule matching has no probability or process-global randomness. Duplicate `(tool_name, invocation_number)` rule selectors are rejected when the fault-injecting executor is constructed.

## Before-call faults

`EXCEPTION`, `RATE_LIMIT`, and `TIMEOUT_BEFORE_CALL` do not invoke the operation. Their records state:

- `underlying_operation_executed = false`
- `underlying_operation_committed = false`
- No underlying result or error
- A caller-visible injected error

`InjectedTimeoutError` states that the operation definitely did not execute. `InjectedRateLimitError` exposes status code 429, a retryable flag, and an optional retry-after value for future configuration.

`LATENCY` also begins before the call, but it delays and then permits the operation to execute. Production uses `asyncio.sleep`; tests inject a fake sleeper and never wait in real time.

## After-call faults

`MALFORMED_RESPONSE` executes the operation and records its actual result, then substitutes only the configured caller-visible result.

`TIMEOUT_AFTER_COMMIT` executes the operation exactly once and waits for successful completion. It records the actual result with both execution and commit set to true, discards that result from the caller's perspective, and raises `AmbiguousToolOutcomeError`. It does not roll back state.

If the underlying operation itself raises before an after-call fault can be applied, the original exception is recorded and re-raised. That invocation is not labeled as an injected after-call fault.

## Actual versus caller-visible outcomes

`ToolInvocation` keeps separate fields for:

- `underlying_result` and `underlying_error`
- `caller_response` and `caller_error`
- `underlying_operation_executed`
- `underlying_operation_committed`, which is `None` when commit status is not knowable

This distinction allows a successful committed operation to coexist with a caller-visible failure. It also prevents an ordinary dependency exception from being mislabeled as a RIFT-injected exception.

## Invocation numbering

Counters are one-based and scoped by experiment identity, run identity, and tool name. Interleaved tools therefore advance independently:

```text
get_order       -> 1
refund_payment  -> 1
refund_payment  -> 2
get_order       -> 2
```

A separate run starts each tool at invocation one, even when the same executor instance handles both contexts. Invocation identifiers are derived deterministically from the run ID, tool name, and invocation number.

## Timing abstractions

Wall-clock timestamps support human-readable evidence. Monotonic time computes duration and avoids wall-clock adjustments. `SystemClock` and `AsyncioSleeper` are production implementations; the protocols permit deterministic fakes in tests.

