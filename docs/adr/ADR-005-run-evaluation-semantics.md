# ADR-005: Run evaluation, comparison, and agent-visible tool outcomes

- Status: Accepted
- Date: 2026-11-01

## Context

ADR-002 says state decides correctness and that an invalid baseline makes a comparison
inconclusive, but left the exact rules to "the core engine". Implementing the runner forced four
decisions that directly affect whether a RIFT verdict can be trusted.

## Decisions

### 1. Outcome is derived in exactly one place

`derive_outcome(invariant_results)` is the only function that produces a `RunOutcome`:
no results → `INCONCLUSIVE`; any `ERROR` → `ERROR`; any `FAIL` → `FAIL`; otherwise `PASS`.
The agent's status and message are not inputs. An adapter crash is recorded but does not decide
the outcome — the state still does.

### 2. Classification crosses the agent's claim with the proven outcome

| | agent claims success | agent does not |
| --- | --- | --- |
| state correct | `correct` | `unconfirmed_success` |
| state incorrect | `silent_failure` | `detected_failure` |

`ERROR`/`INCONCLUSIVE` outcomes classify as `evaluation_error`. This makes the product's central
claim — what the agent says vs. what happened — a first-class, testable output.

### 3. Comparison verdict precedence

1. `baseline_invalid` if the fault-free baseline did not `PASS`.
2. `not_exercised` if no fault rule fired in the faulted run.
3. `resilient` if the faulted run passed, otherwise `degraded`.

Rules that never fired are always listed. Without step 2, a fault aimed at an invocation the agent
never makes would silently produce a "resilient" result.

### 4. The tool gateway hides fault provenance from agents

`ExecutorToolGateway` converts executor results and exceptions into `ToolCallOutcome` values.
`TIMEOUT_BEFORE_CALL` and `TIMEOUT_AFTER_COMMIT` produce *identical* outcomes; injected exceptions
are presented as ordinary dependency errors. A real caller cannot know whether a timed-out
operation executed, so RIFT must not leak that through exception types or messages. The
distinction remains in the `ToolInvocation` evidence, which agents never see.

### 5. Fresh environment per run

Each run gets a new environment instance and a reset. The runner also checks that the baseline and
faulted initial snapshots are equal and match the scenario's declared `initial_state`, so "equivalent
starting state" is verified rather than assumed.

## Consequences

- Verdicts are explainable from structured evidence and are regression-tested as a full
  agent × fault matrix.
- Adapters receive less information than the raw executor exposes. That is intentional.
- The runner owns sequencing and these pure evaluation rules; it imports the fault and invariant
  engines but never scenario or adapter code (enforced by `tests/test_dependency_boundaries.py`).

## Also recorded: `DUPLICATE_REQUEST`

A new `FaultType.DUPLICATE_REQUEST` (after-call) delivers one request to the dependency twice, as an
at-least-once transport might, and shows the caller the first response. `ToolInvocation` gains
`underlying_execution_count` (derived as 0 or 1 by default; must be 2 for this fault). It is kept
distinct from `TIMEOUT_AFTER_COMMIT` (ADR-004): there the *agent* creates the duplicate by retrying;
here the *transport* does, and only server-side idempotency can prevent it.
