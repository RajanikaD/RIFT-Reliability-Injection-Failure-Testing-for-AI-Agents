# Domain model

This document defines the initial conceptual model. It is implementation-neutral: names describe domain responsibilities and do not prescribe database tables or Pydantic class layouts.

## Relationships

```text
Experiment
├── references one Scenario
├── contains zero or more FaultRules
└── produces ExperimentRuns
    ├── records ToolInvocations
    ├── produces one or more StateSnapshots
    └── produces one RunResult
        └── contains InvariantResults for the Scenario's Invariants

AgentAdapter executes the Scenario for an ExperimentRun.
```

## `Experiment`

An immutable, versioned definition of a reliability test. It binds a `Scenario` to run configuration, a deterministic seed, an agent-adapter configuration reference, and a set of `FaultRule` definitions.

An experiment describes intent; it is not an execution record. Executing it creates a baseline `ExperimentRun` and at least one faulted `ExperimentRun` according to the runner's supported plan.

Conceptual fields:

- Identity and definition version.
- Human-readable name and optional description.
- Scenario reference and version.
- Agent adapter kind and non-secret configuration reference.
- Random seed.
- Ordered fault rules.
- Run limits such as an execution deadline or maximum tool invocations.

## `ExperimentRun`

One execution attempt of an experiment in either `BASELINE` or `FAULTED` mode. It records the exact inputs required to interpret and, where possible, reproduce that attempt.

Conceptual fields:

- Run identity and experiment definition reference.
- Mode: baseline or faulted.
- Seed and resolved fault plan.
- Scenario and adapter versions.
- Lifecycle status and timestamps.
- Tool-invocation trace.
- Snapshot references.
- Terminal `RunResult`.
- Failure information when orchestration or execution cannot complete.

A retry of an interrupted run is a new run attempt unless later durable-execution semantics explicitly define resumption.

## `Scenario`

A versioned test case describing the task given to an agent and the controlled environment in which it operates. It defines initial sandbox state, available tools, and required outcome invariants.

Conceptual fields:

- Identity and version.
- Task input presented to the agent.
- Initial-state fixture or fixture reference.
- Tool contract references.
- Ordered invariant definitions.
- Optional scenario-specific execution constraints.

The eventual ecommerce scenario will contain order, payment, inventory, and notification state for `ORD-1001`. It is not implemented in this blueprint.

## `FaultRule`

A declarative rule that selects tool invocations and specifies a fault to inject. Rules are ordered and evaluated deterministically.

Conceptual fields:

- Rule identity.
- Enabled state.
- Match criteria, such as tool name and invocation occurrence.
- `FaultType`.
- Type-specific parameters, such as latency duration or malformed payload shape.
- Optional probability, evaluated with the run-scoped seeded generator.
- Application limit, such as once per run.
- Explicit priority or order.

Conflict behavior when multiple rules match must be defined by the fault engine before implementation; it must never depend on unordered collection iteration.

## `FaultType`

A closed initial vocabulary identifying fault semantics. Planned values are:

| Value | Intended semantics |
| --- | --- |
| `LATENCY` | Delay the caller-visible completion of an invocation. |
| `RATE_LIMIT` | Reject the invocation with rate-limit semantics, such as HTTP 429. |
| `EXCEPTION` | Raise a configured dependency or tool error. |
| `TIMEOUT_BEFORE_EXECUTION` | Report a timeout without executing the underlying operation. |
| `TIMEOUT_AFTER_COMMIT` | Execute and commit the operation, then report a timeout to the caller. |
| `MALFORMED_RESPONSE` | Execute according to configuration but return a syntactically or semantically malformed response. |
| `SCHEMA_DRIFT` | Return a response conforming to a deliberately changed contract. |
| `DUPLICATE_OPERATION` | Cause the underlying operation to be attempted more than once. |

These values define the target vocabulary, not a promise that all are implemented in V0.

## `ToolInvocation`

An append-only record of one attempted tool call as observed at the fault-injection boundary.

Conceptual fields:

- Invocation identity, run identity, and stable run-local sequence number.
- Tool name and contract version.
- Sanitized input or input digest.
- Start and finish times.
- Rules evaluated and selected fault, if any.
- Underlying execution and commit status when observable.
- Sanitized caller-visible output or error.
- Parent correlation data supplied by the adapter.

The record distinguishes the underlying operation's outcome from what the agent observed. This distinction is necessary for ambiguous failures such as timeout after commit.

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

## `RunResult`

The terminal, framework-neutral assessment of one `ExperimentRun`.

Conceptual fields:

- Run identity and terminal status.
- Agent execution outcome.
- Collection of `InvariantResult` values.
- Aggregate outcome: `PASS`, `FAIL`, `ERROR`, or `INCONCLUSIVE`.
- Snapshot and invocation-trace references.
- Execution summary and timing metadata.

An agent completing without an exception does not imply `PASS`; required invariants determine the outcome. `INCONCLUSIVE` covers cases where a valid assessment is unavailable without incorrectly converting uncertainty to success.

## Baseline comparison

Baseline-versus-fault comparison is produced by the experiment runner from two `RunResult` values plus their evidence. It is deliberately not included as a separate initial domain concept in the requested model.

The comparison should report:

- Whether the baseline is a valid control.
- Changes in aggregate outcome.
- Changes for each invariant.
- Differences in relevant state and side-effect counts.
- Faults injected and invocations affected.

If the baseline does not satisfy its required invariants, the faulted run can still retain its own result, but the comparative conclusion is invalid or inconclusive.

## Identity, versioning, and immutability

- Definitions (`Experiment`, `Scenario`, and `Invariant`) are versioned so historical runs retain their meaning.
- Execution evidence (`ToolInvocation`, `StateSnapshot`, `InvariantResult`, and `RunResult`) is append-only after a run is finalized.
- References use stable opaque identifiers rather than names.
- Serialization formats and database schemas are implementation concerns and may evolve without changing these concepts.

