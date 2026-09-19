# ADR-004: Model ambiguous operation outcomes explicitly

- Status: Accepted
- Date: 2026-09-18

## Context

A caller-visible timeout describes missing confirmation, not necessarily the state of the underlying operation. A request can time out before reaching a dependency, or the dependency can execute and commit the operation while its response is delayed or lost. Both cases look like a timeout to an agent, but they leave different system states.

This ambiguity is especially important for non-idempotent operations such as charging a payment method, issuing a refund, creating a shipment, or sending a notification. Retrying after a pre-execution timeout may be necessary. Retrying after an unobserved commit may create duplicate side effects.

## Decision

RIFT models these conditions as distinct fault types:

- `TIMEOUT_BEFORE_CALL` occurs in `FaultPhase.BEFORE_CALL`. The underlying operation does not execute and therefore cannot commit.
- `TIMEOUT_AFTER_COMMIT` occurs in `FaultPhase.AFTER_CALL`. The underlying operation executes and commits, but the caller observes a timeout or error instead of the successful result.

`FaultRule` exposes these semantics declaratively. `ToolInvocation` records the caller-visible outcome separately from whether the underlying operation executed and committed. Model validation rejects invocation evidence that contradicts the selected timeout semantics.

The domain model does not inject either behavior. A later fault executor must implement the declared semantics while preserving this evidence boundary.

## Consequences

### Positive

- A timeout cannot be incorrectly treated as proof that an operation failed.
- Experiments can test whether an agent retries, checks state, uses an idempotency key, or reconciles an ambiguous result.
- Invocation evidence can explain why the caller saw failure while state changed successfully.
- Later scenarios can detect duplicate refunds, messages, or other non-idempotent side effects caused by unsafe retries.

### Negative

- Tool integrations must expose enough information to distinguish execution and commit when that information is knowable.
- Some real dependencies cannot prove commit status immediately; those cases may require an explicit unknown state in a future model revision.
- Fault executors must control both underlying execution and the caller-visible response.

## Alternatives considered

### Represent all timeouts as one fault type

Rejected because it erases the distinction that determines whether retrying is safe and prevents reliable duplicate-side-effect testing.

### Infer commit status from the caller-visible exception

Rejected because the same exception can occur before execution, during execution, or after commit. The exception alone is insufficient evidence.

### Treat after-commit timeout as a duplicate-operation fault

Rejected because the timeout creates ambiguity; a duplicate occurs only if a caller or retry mechanism acts on that ambiguity. Keeping them separate enables RIFT to test recovery and reconciliation behavior rather than assuming a retry.

