# Domain model

This document defines the initial conceptual model and its V0 Pydantic representation in `rift_core`. The models are framework-neutral, strict, and frozen after validation. They do not prescribe database tables or infrastructure behavior.

## Relationships

```text
ExperimentSpec
├── contains one ScenarioSpec
├── contains zero or more FaultRules
└── is executed using an ExecutionContext
    └── produces an ExperimentRunResult
        ├── records ToolInvocations
        ├── may contain a StateSnapshot
        └── contains InvariantResults for the ScenarioSpec's declared invariants

Future AgentAdapter and experiment-runner components will consume these models.
```

## `ExperimentSpec`

An immutable, versioned definition of a reliability test. It binds a `ScenarioSpec` to a deterministic seed and an ordered set of `FaultRule` definitions.

An experiment specification describes intent; it is not an execution record. A future runner will create separate baseline and faulted execution contexts from it.

Conceptual fields:

- Experiment identity, name, and optional description.
- Embedded versioned scenario specification.
- Random seed.
- Ordered fault rules.

Duplicate fault-rule identities and duplicate `(tool_name, invocation_number)` selectors are rejected. Every rule must reference a tool declared by the scenario. Rejecting selector conflicts keeps matching unambiguous until a later fault-engine decision defines composition or priority.

## `ExecutionContext`

The stable identifiers and deterministic inputs for one execution attempt.

Conceptual fields:

- Experiment identity.
- Run identity.
- Random seed.
- `RunMode`: `BASELINE` or `FAULTED`.

Fault rules never match in baseline mode. A retry of an interrupted run will be a new context unless later durable-execution semantics explicitly define resumption.

## `ScenarioSpec`

A versioned test case describing the task given to an agent and the controlled environment in which it operates. It defines initial sandbox state, available tools, and required outcome invariants.

Conceptual fields:

- Scenario identity, name, and positive integer version.
- Task input presented to the agent.
- JSON-compatible initial state.
- Ordered, unique tool names.
- Ordered, unique invariant identities.

The eventual ecommerce scenario will contain order, payment, inventory, and notification state for `ORD-1001`. It is not implemented in this blueprint.

## `FaultRule`

A declarative rule that selects one numbered occurrence of a named tool and specifies a fault to inject. Rules are ordered and evaluated deterministically.

Conceptual fields:

- Rule identity, tool name, and one-based invocation number.
- `FaultType`.
- Derived `FaultPhase`.
- Type-specific parameters: positive latency duration, optional error message, or malformed replacement response.

`matches` returns true only when tool name and invocation number match in `FAULTED` mode. There is no probability field or random selection in this version. Duplicate selectors are rejected by `ExperimentSpec`; future rule composition requires an explicit architectural decision.

## `FaultPhase`

`BEFORE_CALL` behavior occurs before the underlying operation is invoked. `AFTER_CALL` behavior occurs only after the underlying operation has been invoked. Phase is derived from fault type and contradictory configurations are rejected.

## `FaultType`

A closed initial vocabulary identifying fault semantics. Planned values are:

| Value | Intended semantics |
| --- | --- |
| `LATENCY` | Delay the caller-visible completion of an invocation. |
| `RATE_LIMIT` | Reject the invocation with rate-limit semantics, such as HTTP 429. |
| `EXCEPTION` | Raise a configured dependency or tool error. |
| `TIMEOUT_BEFORE_CALL` | Report a timeout without executing the underlying operation. |
| `TIMEOUT_AFTER_COMMIT` | Execute and commit the operation, then report a timeout to the caller. |
| `MALFORMED_RESPONSE` | Execute according to configuration but return a syntactically or semantically malformed response. |

`EXCEPTION`, `RATE_LIMIT`, and `TIMEOUT_BEFORE_CALL` prevent the underlying call. `LATENCY` delays before allowing the call. `MALFORMED_RESPONSE` occurs after a call. `TIMEOUT_AFTER_COMMIT` guarantees that the operation executed and committed before the caller-visible error. These are model semantics only; no executor is implemented yet. Schema drift and duplicate-operation injection remain future fault types.

## `ToolInvocation`

An append-only record of one attempted tool call as observed at the fault-injection boundary.

Conceptual fields:

- Invocation identity, run identity, tool name, and positive invocation number.
- JSON-compatible arguments.
- Applied fault-rule identity, type, and phase, if any.
- Explicit underlying execution and commit flags.
- Caller-visible response or error.

The record distinguishes the underlying operation's outcome from what the caller observed. Validation enforces the two timeout cases: before-call timeouts cannot execute or commit, while after-commit timeouts require both execution and commit plus a caller-visible error.

## `AgentAdapter`

A framework-neutral execution contract, not a persisted entity. It translates between the runner's execution request and a specific agent implementation.

Conceptual operations:

- Identify the adapter kind and version.
- Execute a scenario with a supplied task, tool gateway, run context, and limits.
- Return a normalized completion status, optional agent response, and diagnostic metadata.

The adapter must call tools through the supplied interception boundary. It must not select faults, reset state, evaluate invariants, or persist run results. Provider-specific objects and exceptions are normalized before crossing the boundary.

`ScriptedAgentAdapter` will be the first implementation. It will follow a deterministic sequence of tool actions suitable for engine tests.

## `StateSnapshot`

An immutable, point-in-time observation of scenario-relevant external state.

Conceptual fields:

- Snapshot identity and run identity.
- Capture phase, initially post-run and optionally pre-run for diagnostics.
- Scenario and state-schema versions.
- Capture timestamp.
- Canonically serialized state or typed state reference.
- Integrity metadata such as a digest.

Snapshots contain enough information to evaluate declared invariants. They are observations, not the sandbox's mutable working state.

## `Invariant`

A versioned, deterministic assertion over a snapshot and permitted run evidence. It expresses a required system outcome or side-effect constraint.

Conceptual fields:

- Invariant identity and version.
- Human-readable description.
- Evaluator kind and typed parameters.
- Severity or requirement level if later needed.

Examples include field equality, exact record count, amount equality, and absence of duplicates. The initial implementation should favor typed evaluators over arbitrary code or natural-language judging.

## `InvariantResult`

The result of evaluating one invariant for one run.

Conceptual fields:

- Invariant identity and version.
- Status: `PASS`, `FAIL`, or `ERROR`.
- Concise reason.
- Structured expected and observed values where applicable.
- Evidence references into the snapshot or invocation trace.
- Evaluator error details when status is `ERROR`.

`ERROR` means the invariant could not be evaluated and must not be treated as a pass.

## `ExperimentRunResult`

The terminal, framework-neutral assessment of one execution attempt.

Conceptual fields:

- `ExecutionContext` and aggregate `RunOutcome`.
- Optional diagnostic agent response.
- Collection of `InvariantResult` values.
- Optional state snapshot and ordered tool-invocation evidence.

Invocation and snapshot run identities must match the execution context. An agent completing without an exception does not imply `PASS`; required invariants determine the outcome. `INCONCLUSIVE` covers cases where a valid assessment is unavailable without incorrectly converting uncertainty to success.

## Baseline comparison

Baseline-versus-fault comparison will be produced by the experiment runner from two `ExperimentRunResult` values plus their evidence. It is deliberately not included as a separate initial domain concept.

The comparison should report:

- Whether the baseline is a valid control.
- Changes in aggregate outcome.
- Changes for each invariant.
- Differences in relevant state and side-effect counts.
- Faults injected and invocations affected.

If the baseline does not satisfy its required invariants, the faulted run can still retain its own result, but the comparative conclusion is invalid or inconclusive.

## Identity, versioning, and immutability

- Definitions (`ExperimentSpec`, `ScenarioSpec`, and future invariant specifications) are versioned so historical runs retain their meaning.
- Execution evidence (`ToolInvocation`, `StateSnapshot`, `InvariantResult`, and `ExperimentRunResult`) is immutable after validation.
- References use stable opaque identifiers rather than names.
- Serialization formats and database schemas are implementation concerns and may evolve without changing these concepts.
