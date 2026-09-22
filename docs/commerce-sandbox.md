# Commerce sandbox

## Purpose

The commerce sandbox is a deterministic synthetic business system for exercising RIFT against observable state and side effects. It provides realistic enough order, payment, refund, inventory, and notification behavior to demonstrate duplicate writes, ambiguous outcomes, and safe versus unsafe retries without calling a real ecommerce or payment API.

The sandbox is not an agent, experiment runner, invariant evaluator, or persistence service.

## Dependency boundary

`commerce_demo` does not import or know about the fault engine. It exposes ordinary asynchronous business operations. A caller may place RIFT's tool-execution boundary in front of those operations:

```text
Agent or test
    ↓
RIFT ToolExecutor
    ↓
CommerceSandbox
    ↓
CommerceStateRepository
```

This direction lets the same sandbox execute normally or behind injected failures without embedding reliability-test behavior in the business system.

## Deterministic initial state

Every new in-memory repository and every `reset()` call produces:

| Entity | Initial state |
| --- | --- |
| Order | `ORD-1001`, `CONFIRMED`, total `Decimal("79.99")` |
| Order item | `SKU-HEADPHONES-001`, quantity 1, unit price `Decimal("79.99")` |
| Payment | `PAY-1001`, `CAPTURED`, amount `Decimal("79.99")` |
| Inventory | `SKU-HEADPHONES-001`, available quantity 9 |
| Refunds | None |
| Notifications | None |

Reset also returns refund and notification ID sequences to one and clears all idempotency records.

## Domain and state repository

Commerce entities are strict, frozen Pydantic models. Money uses `Decimal`; float refund inputs are rejected. The repository stores immutable entities by identity and replaces an entity when its state changes.

`CommerceStateRepository` defines the storage operations required by `CommerceSandbox`. `InMemoryCommerceStateRepository` implements that boundary with local dictionaries, deterministic counters, and operation-specific idempotency indexes. It contains no database or external-service integration.

## Supported operations

All business operations are asynchronous:

- `get_order(order_id)` returns an order or raises `OrderNotFoundError`.
- `cancel_order(order_id)` changes `CONFIRMED` to `CANCELLED`. Cancelling an already-cancelled order is deliberately idempotent and returns the existing order without another side effect.
- `refund_payment(payment_id, amount, idempotency_key=None)` creates a successful refund and marks the payment refunded.
- `restore_inventory(sku, quantity)` adds a positive integer quantity. This operation intentionally has no idempotency support.
- `send_confirmation(order_id, message, idempotency_key=None)` creates a cancellation-confirmation notification.

Meaningful business failures use typed commerce-domain errors.

## Refund behavior

Without an idempotency key, every valid request creates a new refund record, even when an equivalent refund already exists or total refund side effects exceed the captured payment. Two `79.99` requests therefore produce `REF-0001` and `REF-0002`, representing `159.98` in refund side effects.

With an idempotency key, the repository stores the request's payment ID and exact `Decimal` amount with the created refund ID. Replaying equivalent data returns the original refund without creating another record. Reusing the key with a different payment or amount raises `IdempotencyConflictError`.

This is request idempotency, not automatic reconciliation or a refund-limit policy.

## Notification behavior

Notifications follow the same pattern. Without a key, repeated calls create independent notification records. With a key, an equivalent order ID and normalized message return the original notification. Reusing the key with different request data raises `IdempotencyConflictError`.

Refund and notification idempotency namespaces are separate.

## Deterministic identifiers

The in-memory repository assigns sequential identifiers:

```text
REF-0001, REF-0002, ...
NOTIF-0001, NOTIF-0002, ...
```

No UUID or wall-clock source participates in identifier generation. `reset()` restarts both sequences.

## Snapshot behavior

`snapshot()` returns a frozen `CommerceSnapshot` containing ordered tuples of all orders, payments, refunds, inventory items, and notifications. Every contained entity is also frozen. Because operations replace stored entities rather than mutating them, a previously captured snapshot does not change when later operations modify repository state.

The snapshot intentionally contains all state needed by the next milestone's invariant evaluation, but it does not evaluate any invariant itself.

## Intentional limitations

- No automatic retries, idempotency-key generation, or reconciliation.
- No refund cap or real payment-provider behavior.
- No idempotency for inventory restoration.
- No database, API, authentication, agent, or experiment orchestration.
- No invariant definitions or reliability scoring.

