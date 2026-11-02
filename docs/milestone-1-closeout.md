# Milestone 1 closeout

- Date: 2026-11-01
- Scope: the repository audit plus the first end-to-end experiment slice (backlog B1–B9, B11)
- Base revision: `677ab21`. Nothing is committed; all work is in the working tree.

## 1. Working-tree provenance

The working tree contains two kinds of uncommitted work. They are told apart by diffing against
a second local checkout outside this repository (the *reference checkout*), at the same `677ab21` with the
**same uncommitted file set** that this repository had when the session started. Its code and
tests were byte-identical to this checkout before any Milestone 1 edits (verified with
`diff -r --strip-trailing-cr`). Line-ending differences (LF in the working tree, CRLF on Git
checkout) are ignored throughout.

### A. Pre-existing uncommitted work (the invariant engine), preserved

| File | State now |
| --- | --- |
| `packages/rift_invariant_engine/**` (README, `__init__`, `contracts`, `invariants`) | Byte-identical to the original |
| `packages/rift_invariant_engine/.../evaluator.py` | Original plus six `# type: ignore[prop-decorator]` comments on `@computed_field` (the documented pydantic/mypy pattern). No behavior change. |
| `examples/commerce_demo/src/commerce_demo/invariants.py`, `__init__.py` | Byte-identical |
| `docs/invariant-evaluation.md`, `docs/architecture.md`, `docs/commerce-sandbox.md` | Byte-identical |
| `tests/test_invariant_engine.py`, `test_commerce_invariants.py`, `test_invariant_fault_integration.py` | Byte-identical |
| `tests/test_dependency_boundaries.py` | Original test function restored verbatim alongside new, stricter parametrized checks |
| `rift_core/domain.py`, `tests/test_domain_models.py`, `pyproject.toml`, `apps/api/Dockerfile`, `README.md`, `docs/domain-model.md` | Original edits intact; Milestone 1 additions layered on top (below) |

During review I found two places where my earlier edits had removed original content: the original
boundary test was replaced, and the README lost its *Design goals*, *System boundaries* and Docker
sections. Both have been restored. The README's boundaries table now has a status column.

### B. Milestone 1 changes, file by file

| Area | File(s) | Change |
| --- | --- | --- |
| Core contracts | `rift_core/contracts.py` *(new)*, `rift_core/__init__.py` | `AgentAdapter`, `ToolGateway`, `ToolCallOutcome`, `ToolErrorKind`, `ToolSpec`, `ToolHandler`, `AgentTask`, `AgentRunOutput`, `AgentStatus` |
| Domain | `rift_core/domain.py` | `FaultType.DUPLICATE_REQUEST`; `ToolInvocation.underlying_execution_count` with validation. Additive only. |
| Fault engine | `rift_fault_engine/executor.py` | Duplicate-request execution path; `_record` accepts an execution count. Additive only. |
| Adapters | `packages/rift_agent_adapters/**` *(new)* | `ScriptedAgentAdapter`, `ScriptStep`, `RetryPolicy`, `Reconciliation` |
| Runner | `packages/rift_experiment_runner/**` *(new)* | `ExperimentRunner`, `ExecutorToolGateway`, `evaluation.py` (outcome derivation, classification, comparison, state diff, fingerprint), report models, text renderer |
| Commerce | `sandbox.py` | Added read-only `get_inventory` and `list_refunds`; `_validate_refund_amount` made type-safe (same behavior) |
| Commerce | `tools.py`, `scenario.py`, `agents.py`, `fault_cases.py` *(new)* | Tool specs and handlers, scenario binding, four agent profiles, ten fault cases |
| CLI | `apps/cli/**` *(new)* | `rift list`, `rift run`, `rift demo`, `--json`, `--spec`, `--strict` |
| Build | `pyproject.toml`, `uv.lock`, `apps/api/Dockerfile` | Packages and `rift` entry point registered; mypy dev dependency and strict config; Dockerfile copies the new packages |
| CI | `.github/workflows/ci.yml` *(new)* | Ruff, format, strict mypy, pytest, demo smoke test on Python 3.11 and 3.12 |
| Tests | `test_tool_gateway`, `test_scripted_adapter`, `test_runner_evaluation`, `test_experiment_lifecycle`, `test_commerce_experiments_e2e`, `test_cli`, `test_business_oracle`, `test_reliability_limits` *(new)*; additions to `test_fault_executor`, `test_domain_models`, `test_dependency_boundaries` | 96 new tests |
| Docs | `implementation-audit.md`, `experiment-runner.md`, `progress-log.md`, `milestone-1-closeout.md`, `ADR-005`, `samples/` *(new)*; `README.md`, `domain-model.md`, `product.md`, `fault-execution.md`, `examples/commerce_demo/README.md` | Stale statements corrected; replaced sentences are listed in the audit |

## 2. Verification evidence

Every check below was run against this checkout. Before the run, each first-party module's
`__file__` was confirmed to resolve inside this checkout (see audit §1 for why
this matters).

| Check | Command | Result |
| --- | --- | --- |
| Tests (editable install) | `pytest -p no:cacheprovider` | **176 passed** |
| Tests (installed wheel, clean venv) | wheel built with `uv build`, installed into a fresh venv, full `tests/` run | **176 passed**; modules imported from that venv's `site-packages` |
| Lint | `ruff check --no-cache .` | clean |
| Format | `ruff format --check --no-cache .` | clean |
| Types | `mypy --no-incremental` (strict, pydantic plugin, `python_version = "3.11"`) | clean, 35 source files |
| Lock file | `uv lock --check` | consistent |
| Packaging | `uv build` | sdist and wheel built; wheel contains all 8 packages and the `rift` entry point |
| Docker (static) | every `COPY` path exists, and every packaged source root is copied | pass |
| 3.11 syntax | ruff `UP` at `py311`; grep for 3.12-only syntax/APIs | none found |

### Independent business oracle (`tests/test_business_oracle.py`)

It runs all 40 agent × fault-case experiments (4 agents × 10 cases, including `none`). It does not
import RIFT's commerce invariants. Instead it re-derives five business rules (R1–R5) from the task
text and fixture and evaluates them on raw JSON state. It also checks six trace↔state consistency
rules (C1–C6) on every baseline and faulted run.

- RIFT's run outcome agrees with the oracle in all 80 runs.
- Each RIFT invariant agrees with its matching business rule in every run.
- **R3 (no over-refund)** is not a RIFT invariant; every R3 violation is still a RIFT `FAIL`.
- **Trace explains state:** every refund and notification in final state was created by a
  recorded, executed invocation, and nothing the trace claims was created is missing. The
  inventory change equals the number of successful restore executions.
- `silent_failure` ⇔ the agent claimed success while a business rule was broken.
- **Sensitivity check:** planting a bug in the `inventory_restored` invariant (`expected=1` → `0`)
  made 3 oracle tests fail. The original file was then restored byte-identical.

### Edge cases (`tests/test_reliability_limits.py`)

| Topic | What the test shows |
| --- | --- |
| Concurrent duplicates | 5 concurrent same-key refunds → 1 refund; 3 keyless → 3. The first holds only because the in-memory check-and-write has no `await` in between (documented limitation). |
| Concurrent invocation order | The fault hits the call that *started* first. The recorder and trace list calls in *completion* order. |
| Reconciliation under concurrency | The real `reconciling_agent` misattributes a concurrent writer's +1 as its own, skips its retry, and reports success with stock 10 instead of 11. A limitation of the strategy, pinned by a test. |
| Ambiguous commit, no fault | A dependency that commits then raises `ConnectionResetError` is recorded as executed, `committed=None` (unknown, not false), not injected. The refund is visible in state. |
| Timeout after commit | Evidence shows committed and executed, with a caller error and no caller response. |
| Invalid baseline (evaluation error) | An invariant that raises → baseline `ERROR`, `evaluation_error`, verdict `baseline_invalid`. |
| Never-triggered faults | A fault on a declared but unused tool → `not_exercised`. A fault on an undeclared tool is rejected when the spec is built. |
| Reproducibility | Two reports differ only in `started_at`, `finished_at`, `duration_ms` and `captured_at`. Fingerprints match across separate processes with `PYTHONHASHSEED` 0 and 12345. |

### Not verified

| Item | Reason |
| --- | --- |
| Python 3.11 runtime | Not installed (only 3.12.14 and 3.14). Static evidence only: mypy targets 3.11, ruff `py311`, no 3.12-only syntax. CI includes 3.11. |
| Docker image build/run | Docker Desktop 29.7.2 is installed but its engine was not running. I did not start it or pull images. |
| GitHub Actions workflow | Never executed; nothing has been pushed. |
| Python 3.14 | Available but not exercised; dependency wheels are not cached for it. |
| Test-code typing | mypy covers source packages only, not `tests/`. |

## 3. Sample report: unsafe retry after an ambiguous commit

Full files: [`samples/retrying--refund-timeout-after-commit.txt`](samples/retrying--refund-timeout-after-commit.txt)
and [`.json`](samples/retrying--refund-timeout-after-commit.json), plus
[`samples/idempotent--inventory-timeout-after-commit.txt`](samples/idempotent--inventory-timeout-after-commit.txt).
Generated by `rift run --agent retrying --fault refund-timeout-after-commit --json ...`.
Timestamps in the JSON vary between runs.

```text
VERDICT: DEGRADED
  Faults were injected and the faulted run ended fail; invariants not satisfied: exactly_one_refund, refund_amount_correct. The agent nevertheless reported success.

FAULTED run  outcome=fail  invariants=3/5  agent=completed  classification=silent_failure
  agent says: Order ORD-1001 was cancelled, refunded, restocked, and the customer notified.
  trace:
     1. cancel_order#1                                 actual: executed           caller saw success
     2. refund_payment#1       [timeout_after_commit]  actual: executed           caller saw error
     3. refund_payment#2                               actual: executed           caller saw success
     4. restore_inventory#1                            actual: executed           caller saw success
     5. send_confirmation#1                            actual: executed           caller saw success

Faulted-run invariant evidence
  exactly_one_refund: Invariant not satisfied.
    expected 1  observed 2
    evidence {"payment_id": "PAY-1001", "refund_ids": ["REF-0001", "REF-0002"]}
  refund_amount_correct: Refund count or total amount is incorrect.
    expected "79.99"  observed "159.98"

State differences (baseline vs faulted final state)
  + refunds[1] = {"amount": "79.99", "idempotency_key": null, "payment_id": "PAY-1001", "refund_id": "REF-0002", "status": "succeeded"}
```

Side-effect evidence for invocation 2, from the JSON report. The operation committed `REF-0001`,
but the caller saw only a timeout:

```json
{
  "fault_type": "timeout_after_commit",
  "underlying_operation_executed": true,
  "underlying_operation_committed": true,
  "underlying_execution_count": 1,
  "underlying_result": {"refund_id": "REF-0001", "amount": "79.99", "status": "succeeded", "...": "..."},
  "caller_response": null,
  "caller_error": "injected timeout after commit"
}
```

The agent was shown `"Timed out waiting for a response from refund_payment."`. The `caller_error`
above is RIFT's evidence record, which agents never see.

## 4. Remaining defects

| ID | Defect | Severity | Where |
| --- | --- | --- | --- |
| M1-D1 | `ExperimentRunResult.outcome` is still caller-settable and unchecked in `rift_core`. Only the runner derives it correctly. | Medium | `rift_core/domain.py` |
| M1-D2 | No run-global start sequence on invocations. Under concurrency, trace order is completion order. | Low (the scripted agent is sequential) | executor / `ToolInvocation` |
| M1-D3 | The commerce `initial_state` is computed from the sandbox's own reset. The runner's "declared state matches reset" check is therefore circular for this scenario and would not catch fixture drift. | Medium | `commerce_demo/scenario.py` |
| M1-D4 | Invariants check end state only. Refunding *before* cancelling, or confirming before refunding, would pass. No ordering invariant uses trace evidence. | Medium | commerce invariants |
| M1-D5 | `AmbiguousToolOutcomeError` exposes `operation_may_have_completed` to any caller that uses the executor directly. The gateway prevents the leak, but nothing enforces using the gateway. | Low | `rift_fault_engine/exceptions.py` |
| M1-D6 | `ExperimentRunner._validate` builds a throwaway environment just to list tool names. | Low | runner |
| M1-D7 | Dockerfile installs without the lock file and runs as root. | Low | `apps/api/Dockerfile` |

## 5. Known limitations (by design for now)

- The seed is recorded but has no effect; there are no probabilistic or multi-seed runs (B10).
- One scenario (commerce) and one adapter type (scripted). No real LLM adapter.
- Reconciliation and in-memory idempotency are correct only for a single sequential writer.
- `LATENCY` faults really sleep in the CLI.
- No persistence beyond `--json`. No experiment API or dashboard.
- The sandbox does not cap refunds at the captured amount, so over-refunds are detected rather than
  prevented.

## 6. Proposed next milestone

**Milestone 2 — evidence hardening (before B10).** It is small, has no new feature surface, and
B10 relies on all of it:

1. Get approval to commit (suggested split: pre-existing invariant-engine work first, then
   Milestone 1), push a branch, and see CI pass on 3.11 and 3.12.
2. Verify the Docker image once the engine is running. Make the Dockerfile install from the lock
   file and run as a non-root user (M1-D7).
3. M1-D1: validate in `ExperimentRunResult` that `outcome` matches `invariant_results`.
4. M1-D3: replace the self-derived commerce `initial_state` with a checked-in fixture.
5. M1-D2: add a run-global `sequence_number` to `ToolInvocation`, assigned at call start.
6. M1-D4: add one trace-aware ordering invariant ("refund only after cancellation") using
   `InvariantEvaluationContext.evidence`, and prove it with a scripted agent that refunds first.

**Then Milestone 3 — B10:** seeded, order-independent probabilistic rule selection and multi-seed
experiment aggregation. Its correctness depends on the sequence numbers and fingerprints above.
