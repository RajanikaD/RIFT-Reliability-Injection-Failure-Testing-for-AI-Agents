# Product definition

## Purpose

RIFT tests the reliability of tool-using AI agents under controlled failure conditions. It injects faults into tool calls or external-dependency boundaries, executes an agent, and verifies the resulting system state independently of the agent's narrative response.

The central question is:

> Given the same task and starting state, does the agent still produce an acceptable system outcome when specified failures occur?

## Problem statement

Agent evaluations commonly score generated text, tool-call selection, or a single expected trajectory. Those signals do not establish that the target system reached a correct state. An agent can report success after a failed operation, retry a committed operation and create a duplicate, or partially complete a multi-step task.

RIFT treats external state and recorded side effects as the source of truth. It compares a fault-free baseline with one or more reproducible faulted runs and reports which outcome invariants held.

## Target users

- Engineers developing agents that call APIs, databases, queues, or business tools.
- Reliability engineers testing retry, idempotency, timeout, and recovery behavior.
- Teams evaluating agent frameworks without coupling their reliability tests to one framework.

## Product capabilities

The planned product will:

1. Define a scenario, its initial state, task, tools, and outcome invariants.
2. Execute a fault-free baseline from a reset environment.
3. Execute faulted variants from the same initial state.
4. Inject deterministic faults at selected tool invocations.
5. Capture invocation traces and post-run state snapshots.
6. Evaluate invariants against actual state and side effects.
7. Compare baseline and faulted outcomes with explicit evidence.

## Planned fault types

- Added latency.
- Rate limiting, including HTTP 429 semantics.
- Exceptions.
- Timeout before execution, where the operation did not run.
- Timeout after commit, where the operation succeeded but the caller did not receive confirmation.
- Malformed tool responses.
- Schema drift.
- Duplicate operations.

The initial core need not implement every listed type. `FaultType` provides a stable vocabulary, while each roadmap phase states which behaviors are implemented.

## First demo scenario

The first local demo will eventually model an ecommerce support agent receiving this instruction:

> Cancel order ORD-1001, refund the customer, restore inventory, and send confirmation.

The sandbox will expose controlled ecommerce operations and inspectable state. Illustrative invariants are:

- `order.status == CANCELLED`
- Exactly one refund exists for the order.
- The refund amount equals the order total.
- Inventory is restored once.
- Exactly one confirmation is sent.

These are acceptance targets for a future milestone, not functionality included in the current repository.

## Success criteria

A RIFT experiment is useful when it provides:

- Reproducibility: the same experiment configuration, seed, adapter, and initial state select the same faults and produce the same deterministic test behavior.
- Outcome evidence: every invariant result identifies the inspected state and reason for pass, fail, or error.
- Isolation: baseline and faulted runs start from equivalent reset state.
- Traceability: injected faults can be related to tool invocations and invariant results.
- Portability: the core can run an adapter without importing its agent framework.

Reproducible fault selection does not imply deterministic behavior from a nondeterministic external agent or dependency. RIFT records the inputs needed to distinguish those concerns.

## Non-goals for the initial vertical slice

- Production traffic fault injection.
- Distributed or multi-region execution.
- A general-purpose workflow engine.
- LLM-based grading as the source of truth for system correctness.
- Support for every agent framework.
- Hosted multi-tenancy, authentication, or billing.
- Full OpenTelemetry, Langfuse, or Temporal integration.

## Constraints

- The core cannot depend on OpenAI, LangChain, LangGraph, or another agent framework.
- Framework integrations must implement the `AgentAdapter` boundary.
- The first adapter must be deterministic and require no paid model API.
- Major architectural decisions require an ADR before implementation changes the documented design.
- Secrets and API keys must not be committed.

