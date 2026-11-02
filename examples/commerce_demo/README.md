# Commerce demo

A deterministic, synthetic ecommerce scenario for RIFT: order `ORD-1001`, payment `PAY-1001`, one
SKU of inventory, refunds and notifications.

| Module | Contents |
| --- | --- |
| `models`, `repository`, `sandbox`, `errors` | Immutable entities, resettable in-memory state, async operations with request idempotency for refunds and confirmations. No dependency on RIFT's fault engine. |
| `invariants` | The five outcome invariants for the cancellation task. |
| `tools` | JSON tool specs and handlers that expose sandbox operations to agents. |
| `scenario` | `CommerceScenarioBinding` and `COMMERCE_SCENARIO` for the experiment runner. |
| `agents` | Four scripted agent profiles: naive, retrying, idempotent, reconciling. |
| `fault_cases` | Ten named fault cases used by `rift demo` and `rift run --fault`. |

The sandbox itself stays ignorant of fault injection; everything RIFT-specific is composition code
layered on top.
