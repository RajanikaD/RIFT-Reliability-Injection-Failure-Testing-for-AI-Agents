# Invariant evaluation

## Purpose

RIFT determines correctness from observable system state. An agent response such as “the order
was cancelled and refunded” is diagnostic text, not proof that the required operations occurred
exactly once. Invariants independently inspect immutable state snapshots and produce structured
results.

The invariant engine is framework-neutral. `rift_invariant_engine` depends on `rift_core`; it does
not import the commerce example, an agent framework, or a model provider. Scenario-specific
packages define selectors and invariant sets on top of the generic engine.

## Evaluation context

`InvariantEvaluationContext` supplies both `before_state` and `after_state`. Final-state checks use
the after snapshot. Transition checks use both snapshots—for example, the commerce inventory
invariant verifies an increase of exactly one instead of comparing against a hardcoded terminal
quantity. Evaluation does not mutate either snapshot.

The context may include sanitized structured run evidence. Invariants must opt in to using it;
agent output has no implicit effect on pass/fail status.

## Invariant contract

An `Invariant` has a stable `name`, a human-readable `description`, and an `evaluate` method. The
method receives an evaluation context and returns the shared `rift_core.InvariantResult`. Generic
field, count, exact-number, and predicate invariants use explicit selectors rather than reflection.

Evaluation is deterministic: the evaluator runs the configured tuple in order, and selectors do
not perform probabilistic selection. Results preserve configured order.

## Results and errors

Every result contains:

- the invariant identifier and description;
- `PASS`, `FAIL`, or `ERROR` status;
- a concise message;
- JSON-safe expected and observed values where applicable; and
- deliberately selected structured evidence.

Exact `Decimal` values are represented as strings in results so serialization does not introduce
binary floating-point changes.

`FAIL` means evaluation completed and the required condition did not hold. `ERROR` means the
invariant could not be evaluated. An unexpected exception becomes an `ERROR` result with the
exception type and message, and the evaluator continues with later invariants. Errors are never
treated as passes.

Evidence should contain only the minimum identifiers and measurements required to explain the
result. Raw external payloads and potentially sensitive data are not included by default.

## Aggregate summary

`InvariantEvaluationSummary` reports ordered results plus `total`, `passed`, `failed`, `errors`,
and `all_passed`. `all_passed` is true only for a non-empty result set in which every result passed.
The transparent `correctness_ratio` is `passed / total`; `FAIL` and `ERROR` results remain in the
denominator. An empty result set has a ratio of `0.0` and is not considered all-passing.

No invariant weighting or branded reliability score is applied.

## Commerce scenario

The commerce example defines five checks in stable order:

1. `order_cancelled`
2. `exactly_one_refund`
3. `refund_amount_correct`
4. `inventory_restored`
5. `single_confirmation`

`refund_amount_correct` requires both exactly one matching refund and a total of `79.99`. This
prevents duplicate refunds from passing an amount check through an accidental aggregation rule.
`inventory_restored` compares before and after quantities and requires a delta of exactly one.

The bound scenario (`commerce_demo.ordering.commerce_scenario_invariants`, scenario version 2)
adds a sixth, trace-aware check, `refund_after_cancellation`. A final state records what exists,
not when it came to exist, so ordering can only be judged from trace evidence. The runner supplies
that evidence in `InvariantEvaluationContext.evidence`; the invariant opts in, uses what actually
executed rather than what the caller saw, and raises (becoming `ERROR`) if evidence is missing.
See [ADR-006](adr/ADR-006-evidence-hardening.md).

## Why there is no LLM judge

This milestone evaluates typed, observable conditions. An LLM judge would add non-determinism and
could mistake plausible prose for correct external state. Natural-language evaluation may later be
useful for separate qualitative assertions, but it is not part of the deterministic outcome engine.
