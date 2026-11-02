# RIFT invariant engine

`rift_invariant_engine` evaluates explicit, deterministic invariants against before and after
state. It depends on `rift_core` for result models and has no dependency on agent frameworks or
scenario-specific models.

Scenario packages define their own selectors and invariant sets on top of this package.
