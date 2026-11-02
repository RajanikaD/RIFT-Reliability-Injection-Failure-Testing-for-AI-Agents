# Experiment runner

## Lifecycle

```text
validate experiment ↔ binding (id/version, invariant ids, tool names, then full equality)
for mode in (baseline, faulted):
    new environment → reset → snapshot "before" (checked against the experiment's declared
                                                  initial_state, loaded from a checked-in fixture)
    new FaultInjectingToolExecutor(experiment rules) + recorder      # rules never match baseline
    ExecutorToolGateway(executor, scenario tool handlers, run context, call budget)
    adapter.run(task, gateway)          # crash → AgentStatus.CRASHED, run continues
    snapshot "after" → InvariantEvaluator(before, after, evidence=invocation_evidence(trace))
    derive_run_outcome (enforced by ExperimentRunResult) → classify → fingerprint
assert baseline.initial_state == faulted.initial_state
compare(baseline, faulted, rules) → verdict
```

Both runs use the same executor class. The only difference is `RunMode`, so the baseline exercises
the same code path minus fault matching.

## Packages

| Package | Role |
| --- | --- |
| `rift_core.contracts` | `AgentAdapter`, `ToolGateway`, `ToolCallOutcome`, `ToolSpec`, `AgentTask`, `AgentRunOutput` |
| `rift_agent_adapters` | `ScriptedAgentAdapter` with `RetryPolicy`, response validation and `Reconciliation` |
| `rift_experiment_runner` | `ExperimentRunner`, `ExecutorToolGateway`, pure evaluation functions, report models, text rendering |
| `commerce_demo.scenario` | `CommerceScenarioBinding`, `COMMERCE_SCENARIO`, `commerce_experiment()` |
| `commerce_demo.agents` | Four scripted agent profiles |
| `commerce_demo.fault_cases` | Ten named fault cases |
| `rift_cli` | `rift list`, `rift run`, `rift demo` |

## Scenario binding

A scenario plugs into the runner by implementing two small protocols:

- `ScenarioEnvironment`: `reset()`, `snapshot()`, `snapshot_json(state)`, `tool_handlers()`,
  `tool_specs()`.
- `ScenarioBinding`: `spec`, `create_environment()`, `invariants()`.

Tool handlers take JSON-compatible arguments and return JSON-compatible results, so the same
handlers can later be exposed to a model provider's tool-calling API.

## Report

`ExperimentReport` (Pydantic, JSON round-trippable) contains the experiment spec, adapter identity,
both `RunReport`s and the `Comparison`. Each `RunReport` holds the core `ExperimentRunResult`
(invocations, final `StateSnapshot`, invariant results, agent response), the agent's normalized
output and transcript, the classification, the initial state, which rules fired, and a fingerprint.

The **fingerprint** is a SHA-256 over timing-free, RIFT-controlled evidence: invocation sequence,
arguments, fault applied, execution/commit evidence, final state, invariant statuses and agent
status. Two runs with the same inputs must have the same fingerprint; tests enforce this.

The **state diff** compares baseline and faulted *final* states structurally and reports added,
removed and changed values (for example `+ refunds[1] = {...}` for a duplicate refund).

## Trace evidence and ordering

`invocation_evidence` gives invariants each invocation's tool, number, `sequence_number` (start
order), `completion_position`, `completed_before_start`, and whether it executed and succeeded.
"A happened-before B" means A's `completion_position` ≤ B's `completed_before_start`. The commerce
`refund_after_cancellation` invariant uses this, so a refund requested while the cancellation is
still in flight fails even if it completes second.

## Determinism and the seed

Fault selection is deterministic because rules target an explicit `(tool_name, invocation_number)`
and invocation numbering is per run and per tool. The experiment seed is recorded in every context
but is not yet consumed: there are no probabilistic rules. Backlog item B10 proposes seeded,
order-independent selection (hash of `seed, rule, tool, invocation`) for multi-seed experiments.

## Known limitations

- One faulted run per experiment; no multi-seed or fault-matrix object in the core yet (the CLI's
  `demo` builds the matrix by looping).
- Reports are not persisted beyond the optional `--json` file.
- `LATENCY` faults really sleep unless a `Sleeper` is injected (tests inject a no-op).
- Only the commerce scenario is registered in the CLI.
- Happens-before evidence comes from in-process counters in one executor; it is not a distributed
  clock.
- Scenarios that declare an empty `initial_state` skip the starting-state check (kept for
  lightweight test scenarios); the commerce scenario always declares one.
