# Commerce demo

This example provides a deterministic, synthetic ecommerce environment for exercising RIFT's reliability behavior. It contains immutable business entities, a resettable in-memory state repository, asynchronous operations, explicit idempotency behavior, and detached state snapshots.

It intentionally has no agent, experiment orchestration, invariant evaluation, persistence, external API, or dependency on the RIFT fault engine.
