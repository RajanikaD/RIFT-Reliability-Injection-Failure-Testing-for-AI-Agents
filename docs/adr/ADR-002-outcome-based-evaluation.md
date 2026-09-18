# ADR-002: Evaluate observable outcomes, not agent claims

- Status: Accepted
- Date: 2026-09-18

## Context

An agent can state that a task succeeded even when a dependency failed, a timeout concealed a committed operation, only part of a multi-step task completed, or a retry created duplicate side effects. Textual correctness and trajectory similarity therefore do not establish system correctness.

RIFT needs evaluation semantics that remain meaningful across agent frameworks and response styles.

## Decision

RIFT will determine run success primarily by evaluating explicit `Invariant` definitions against independently captured `StateSnapshot` data and permitted run evidence.

Each invariant produces a structured `InvariantResult` with `PASS`, `FAIL`, or `ERROR`, a reason, and evidence. Required invariant results determine the aggregate `RunResult`. The agent's final response may be retained for diagnostics but is not proof that an operation occurred.

Experiments will use a fault-free baseline as a control and compare it with faulted runs. Each run is evaluated independently before comparison. A baseline that fails required invariants is not a valid control and makes the comparative conclusion invalid or inconclusive.

The first evaluators should be typed and deterministic. Natural-language or LLM-based grading may later supplement diagnostics but cannot be the sole authority for externally observable system state.

## Consequences

### Positive

- Results reflect business state and side effects rather than persuasive output.
- Duplicate, partial, and ambiguous post-commit behavior can be detected.
- Evaluation is portable across models, prompts, and frameworks.
- Failures can include concrete expected-versus-observed evidence.

### Negative

- Each scenario requires an inspectable environment and explicit invariants.
- Snapshot schemas and evaluators require versioning.
- Some qualitative tasks do not have sufficient machine-observable state and may remain outside initial scope.

## Guardrails

- A successful adapter completion never automatically implies a passing run.
- Evaluation errors must remain distinguishable from invariant failures and must never be coerced to passes.
- Snapshot capture must be independent of the agent's self-report.
- The system must preserve the distinction between underlying operation outcome and caller-visible response.

## Alternatives considered

### Grade only the final response with an LLM

Rejected because a plausible statement can contradict actual system state and grading introduces another nondeterministic model into the correctness decision.

### Require an exact expected tool-call sequence

Rejected as the primary evaluation because multiple valid trajectories can reach the same correct outcome, while an expected-looking trajectory can still produce an incorrect state.

