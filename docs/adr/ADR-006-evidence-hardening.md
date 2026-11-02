# ADR-006: Evidence hardening — independent declarations, trace-aware invariants, causal order

- Status: Accepted
- Date: 2026-11-01
- Supersedes: nothing; extends ADR-002, ADR-004 and ADR-005

## Context

The Milestone 1 closeout found that some verification steps looked rigorous but could not fail
(M1-D3), that end-state invariants cannot express *when* something happened (M1-D4), that the core
result model trusted its producer (M1-D1), and that the trace had no run-global start order
(M1-D2). Each of these lets RIFT report confidence it has not earned.

## Decisions

### 1. A check must compare against an independent source

A scenario's declared `initial_state` is a reviewed contract loaded from a checked-in fixture
(`commerce_demo/fixtures/initial_state.json`), never computed from the sandbox it verifies. The
runner verifies each run's reset state against the **experiment's own** declared scenario, and
`_validate` requires that declaration to equal the bound scenario field for field. A spec file
cannot silently run against a different starting state.

### 2. Invariants may opt in to trace evidence

The runner passes `invocation_evidence(trace)` in `InvariantEvaluationContext.evidence`. It
describes what **actually executed** — not what the caller saw — so a refund whose response was
lost still counts. Invariants that need evidence and do not receive it raise, which the evaluator
records as `ERROR`; missing evidence can never produce `PASS`. The generic invariant engine is
unchanged; the ordering invariant lives with the commerce scenario.

### 3. Order means happens-before, not completion order

Each `ToolInvocation` records `sequence_number` (run-global start order) and
`completed_before_start` (how many of the run's invocations had finished when it started).
A happened-before B iff A's completion position ≤ B's `completed_before_start`. Completion order
alone is wrong for overlapping calls: a refund requested while the cancellation was still in
flight can complete second and look correctly ordered. The ordering invariant therefore judges the
agent's *decision* to call (it must wait for the cancellation), which is what the agent controls.

`completed_before_start` is one field beyond the backlog's literal "sequence number". It is the
minimum extra fact needed to express happens-before for concurrent calls and is optional, so
older records remain valid.

### 4. The outcome rule lives in the core model

`rift_core.derive_run_outcome` is the single rule. `ExperimentRunResult` rejects an `outcome` that
contradicts its `invariant_results`. With no results, only `INCONCLUSIVE` or `ERROR` are allowed.
`rift_experiment_runner.derive_outcome` remains as a compatible alias.

### 5. Versioned scenarios change version when their meaning changes

Adding `refund_after_cancellation` changes what a passing run means, so the commerce scenario is
now version 2. Version 1 results remain interpretable as "state invariants only".

### 6. The image is reproducible and unprivileged

The API image installs with `uv sync --locked` (fails if `pyproject.toml` and `uv.lock` disagree),
installs the project non-editable, excludes dev extras, and runs as UID 10001. A static policy
test enforces this without a Docker engine; CI builds and smoke-tests the real image.

## Consequences

- Fingerprints change between Milestone 1 and 2 runs because sequence evidence and a sixth
  invariant are included. Fingerprints are only comparable within one RIFT/scenario version.
- Scenario authors must maintain a fixture by hand. That friction is the point: a fixture change is
  a reviewed diff.
- Ordering checks rely on the executor's in-process counters. A future distributed runner needs an
  equivalent causal clock; wall-clock timestamps are not a substitute.
