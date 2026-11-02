# Milestone 2: evidence hardening

- Date: 2026-11-01
- Baseline: the accepted Milestone 1 closeout ([milestone-1-closeout.md](milestone-1-closeout.md))
- Scope: M1-D3, M1-D4, M1-D1, M1-D2, M1-D7, CI preparation, and the commit plan. Out of scope:
  B10, persistence, API, dashboard, M1-D5, M1-D6.
- Decisions: [ADR-006](adr/ADR-006-evidence-hardening.md)

Method per defect: write a test that demonstrates the defect, run it against unchanged code and
record the failure, implement the smallest fix, then re-run the test and the full suite.

## D3 — circular starting-state verification

**Problem.** `COMMERCE_SCENARIO.initial_state` was computed by resetting the sandbox, and the runner
compared the sandbox's reset state against it. Comparing X with X cannot fail, so an edit to the
fixture would change what every experiment tests with no signal. Also, the runner compared only
the scenario id and version of an experiment's own declaration, so a spec file declaring a
different starting state still ran.

**Before** (`tests/test_starting_state.py` on unchanged code):

```text
FAILED test_a_changed_sandbox_fixture_is_detected                     DID NOT RAISE
FAILED test_an_experiment_declaring_a_different_starting_state_is_rejected  DID NOT RAISE
FAILED test_declared_starting_state_is_loaded_from_a_checked_in_fixture  FileNotFoundError
```

**Fix.** The declaration is loaded from `commerce_demo/fixtures/initial_state.json`, hand-written
from the documented fixture table and schema-validated at import. The runner verifies reset state
against the **experiment's** declaration and requires that declaration to equal the bound scenario
field by field.

**After.** 4/4 pass. A drifted fixture now fails fast with a path-level message:

```text
ExperimentConfigurationError: commerce.cancel_order reset state differs from its declared
initial_state at: inventory[0].available_quantity
```

## D4 — missing order-of-operations invariant

**Problem.** Every invariant read only the final state. A final state records what exists, not when
it came to exist, so an agent that refunded before cancelling reached a state identical to a
correct agent's and passed.

**Before:** `refund-first agent baseline outcome = pass` (five invariants, all passing).

**Fix.** The runner passes trace evidence (`invocation_evidence`) into each invariant's context. A
new commerce invariant, `refund_after_cancellation`, opts in to it. It judges by what **executed**,
not what the caller saw, and errors (never passes) if evidence is missing. The scenario moves to
version 2 because its invariant set changed. The original five-invariant
`commerce_cancellation_invariants()` is unchanged for existing callers.

**After.** `tests/test_ordering_invariant.py` 5/5:

- The refund-first agent fails on ordering while its other five invariants pass.
- A refund that never executed (timeout before the call) does not count as too early.
- A refund whose response was lost (timeout after commit) **does** count, although the agent
  believes it never happened.
- Missing evidence produces `ERROR`.

The independent oracle gained rule R6, computed from raw `ToolInvocation` records, and agrees in all
80 matrix runs. Sample: [samples/m2/refund-first--ordering-violation.txt](samples/m2/refund-first--ordering-violation.txt).

## D1 — outcome trusted from its producer

**Problem.** `ExperimentRunResult.outcome` was a free field. The runner derived it correctly, but
any other producer could store `PASS` next to failing invariants.

**Before:** `accepted outcome = pass with invariant status fail`.

**Fix.** `rift_core.derive_run_outcome` is the single rule, and `ExperimentRunResult` rejects
contradictions. With no invariant results, only `INCONCLUSIVE` or `ERROR` are allowed. The
runner's `derive_outcome` delegates to it (kept for compatibility).

**After.** `tests/test_run_result_validation.py` 10/10. All existing producers already complied, so
no other code changed.

## D2 — no run-global start order

**Problem.** Invocation numbers were per tool, and the trace was recorded in completion order. Two
overlapping calls can complete in either order while neither waited for the other, so completion
order cannot answer "had the cancellation finished when the refund was requested?". D4's first
implementation used completion order and inherited this flaw.

**Before.** A concurrent agent that fires cancel and refund together, with the refund slower, was
judged correctly ordered (`PASS` where `FAIL` is right). The other three tests failed with
`AttributeError: ... no attribute 'sequence_number'`.

**Fix.** The executor assigns each invocation a run-global `sequence_number` at start and records
`completed_before_start`. A happened-before B iff A's completion position ≤ B's
`completed_before_start`. Both fields are optional on `ToolInvocation`, so older records validate.
Reports show `seq` beside the completion-ordered trace.

**After.** `tests/test_invocation_sequencing.py` 4/4. The concurrent ordering violation now fails
with evidence `cancel_completed_at: [1]`, `refund_started_after_completions: [0]`. Sample:
[samples/m2/concurrent--overlapping-cancel-and-refund.txt](samples/m2/concurrent--overlapping-cancel-and-refund.txt).

## D7 — unpinned, root container

**Problem.** The image ran `pip install .`, ignoring `uv.lock`, so builds could resolve different
versions over time. It also ran as root.

**Fix.** `uv sync --locked --no-install-project`, then sources, then `uv sync --locked
--no-editable`; uv pinned to 0.11.17; dev extras excluded; UID 10001; container healthcheck.

**Evidence.**

| Check | Where | Result |
| --- | --- | --- |
| Static policy (lock copied, `--locked` syncs, no `pip install`, non-root, every packaged source copied) | `tests/test_dockerfile.py`, local | Pass. The same check reports all four defects in the Milestone 1 Dockerfile. |
| Dockerfile's two `uv sync` steps in a clean directory | local, Windows, Python 3.12 | Both succeed; non-editable install; no dev tools; CLI verdict `RESILIENT` |
| `docker build`, non-root `id -u`, `/health`, CLI in image | CI `docker` job | **Not run.** No local engine; requires a push. |

## CI

The workflow runs a `check` job on 3.11 and 3.12 (locked install, ruff, format, strict mypy,
pytest, demo smoke test, `uv build`, wheel-fixture check). A `docker` job then builds and
smoke-tests the image.

| | Local evidence | CI evidence |
| --- | --- | --- |
| `check` on 3.12 | Every step replayed in a clean copy (Windows): 201 passed, all green | Pending push |
| `check` on 3.11 | Not available locally; mypy targets 3.11 and no 3.12-only syntax is used | Pending push |
| `docker` | Static policy and locked-sync replay only | Pending push |
| Workflow file | Parsed with PyYAML; jobs, matrix and `needs` checked | Pending push |

## Remaining limitations (accurate as of this milestone)

- **Idempotency is in-memory.** Concurrent same-key refunds are deduplicated only because the
  sandbox's check-and-write has no `await` between them. A real store needs a unique constraint or
  transaction. Pinned by a test.
- **Reconciliation assumes a single writer.** Delta-based reconciliation misattributes a
  concurrent writer's change as its own (stock 10 instead of 11). Pinned by a test; happens-before
  evidence does not fix this, because the misattribution lives in the agent's strategy.
- **Happens-before is in-process.** The counters live in one executor; a distributed runner needs
  a real causal clock.
- **Ordering covers one rule.** Only "refund after cancellation" is checked. "Confirm only after
  refund" is a candidate, not implemented.
- **Seed** still has no effect (B10).
- **Empty `initial_state`** skips the starting-state check (for lightweight test scenarios).
- **Fingerprints** differ from Milestone 1 because sequence evidence and a sixth invariant are
  hashed; they are comparable only within one RIFT and scenario version.
- **Open:** M1-D5 and M1-D6.
