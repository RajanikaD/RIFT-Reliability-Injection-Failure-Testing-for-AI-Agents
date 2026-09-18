# ADR-003: Implement a deterministic scripted agent first

- Status: Accepted
- Date: 2026-09-18

## Context

The engine needs to prove fault interception, orchestration, reset isolation, and invariant evaluation before introducing model-provider cost and nondeterminism. Starting with a live agent SDK would make failures harder to attribute: a test could change because of engine behavior, model behavior, provider availability, or prompt variation.

The adapter contract also needs an implementation that can be exercised in unit and integration tests without credentials or network access.

## Decision

The first `AgentAdapter` implementation will be `ScriptedAgentAdapter`.

It will execute a predefined, deterministic sequence of tool actions and simple branches based on normalized tool outcomes. Its purpose is to exercise the same adapter and intercepted tool boundary that later framework adapters will use. Given the same script, inputs, sandbox state, fault configuration, and seed, its behavior must be reproducible.

An OpenAI Agents SDK adapter will be added only after the local engine and adapter contract are validated.

## Consequences

### Positive

- Core tests require no API keys, paid calls, or network availability.
- Failures are reproducible and attributable to RIFT-controlled behavior.
- The adapter interface is tested before it is shaped by one provider SDK.
- Continuous integration can run the full initial suite predictably.

### Negative

- A scripted adapter does not demonstrate model reasoning or realistic prompt behavior.
- Scripts may need explicit primitives for retry and branching behavior.
- A later live adapter may reveal missing normalization requirements in the initial contract.

## Guardrails

- The scripted adapter must use the public `AgentAdapter` and tool-interception contracts; it cannot call sandbox internals directly.
- It must not contain fault-selection or invariant-evaluation logic.
- Test scripts must describe agent actions, not encode expected results into the evaluator.
- Provider-specific concepts must not be added to the shared contract merely to prepare for a future adapter.

## Alternatives considered

### Implement the OpenAI Agents SDK adapter first

Rejected because model and network nondeterminism would obscure validation of the core engine and add credentials and cost to early tests.

### Test the runner without any adapter abstraction

Rejected because it would leave the primary integration boundary unvalidated and invite later architectural coupling.

