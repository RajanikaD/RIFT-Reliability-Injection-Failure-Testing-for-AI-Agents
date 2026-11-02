# Implementation audit

- Audit date: 2026-11-01
- Audited revision: `677ab21` plus the uncommitted invariant-engine work present in the working tree
- Method: read every tracked source, test, and document; ran the test suite and linters; compared
  documentation claims with code. Nothing below is inferred from the README alone.

## 1. Verified baseline

| Check | Result |
| --- | --- |
| `pytest` (Python 3.12.14, local `.venv`) | 80 passed, 0 failed, 0.9 s |
| `ruff check .` | clean |
| `ruff format --check .` | clean (46 files) |
| Type checking | not configured |
| CI | none |

**Environment finding.** The local `.venv` (ignored by Git) was copied from another checkout:
its editable install resolved `rift_core` and the other packages from a second local
checkout outside this repository (the *reference checkout*), not from this repository. The baseline test run
therefore imported *that* copy. A diff showed the two copies were identical at audit time, so the
80-pass result stands, but any later edit here would have been silently untested. The editable
install was rebuilt to point at this checkout. Lesson: check `module.__file__` before trusting a
green suite in an inherited environment; CI from a clean checkout prevents this class of error.

Git history has four commits (scaffold → domain model → fault executor → commerce sandbox). The
invariant engine (`packages/rift_invariant_engine`, `commerce_demo/invariants.py`,
`docs/invariant-evaluation.md`, four test files, and small edits to `domain.py`, README and docs)
exists **only as uncommitted work**. It is tested and passes, so it is treated as part of the
baseline, but it should be committed as its own reviewable change.

## 2. What is fully implemented

| Component | Evidence | Assessment |
| --- | --- | --- |
| `rift_core` domain models | `domain.py`, 14 tests | Strict, frozen Pydantic models. `ToolInvocation` validation enforces the timeout-before-call / timeout-after-commit evidence rules from ADR-004. Solid. |
| Fault executor | `rift_fault_engine/executor.py`, 13 tests | Six fault types with correct execute/commit semantics; per-run, per-tool one-based numbering; injectable clock and sleeper; recorder captures evidence even when the underlying exception is re-raised. Solid. |
| Commerce sandbox | `commerce_demo/*`, 22 tests | Deterministic reset, detached frozen snapshots, `Decimal` money, request idempotency for refunds and notifications with conflict detection, deliberately non-idempotent inventory restore. Solid. |
| Invariant engine (uncommitted) | `rift_invariant_engine/*`, 18 tests | Typed selector-based invariants, before/after context, ERROR never coerced to PASS, evaluator continues after exceptions. Solid. |
| Commerce invariants (uncommitted) | `commerce_demo/invariants.py` | Five invariants; refund-amount check requires *exactly one* refund so duplicates cannot pass by aggregation; inventory checks the delta, not a hard-coded value. |
| API | `GET /health` only | Works; no experiment endpoints. |

## 3. Missing or unconnected

These are the gaps between the documented product and the code. Each item is verified absent.

1. **No experiment runner.** Nothing resets a scenario, runs a baseline, runs a faulted variant,
   evaluates both, or compares them. `ExperimentRunResult` and `RunOutcome` are never produced by
   code. This is the core of the product and is the top priority.
2. **No `AgentAdapter` contract or `ScriptedAgentAdapter`.** Documented in ADR-003 and the domain
   model; no code exists.
3. **No tool gateway.** Nothing binds sandbox operations to named tools behind the executor or
   normalizes injected exceptions into agent-visible tool results. Existing integration tests call
   the executor by hand.
4. **No baseline comparison**, no handling of an invalid baseline, and no detection of fault rules
   that never fired.
5. **No CLI, report, or demo command.** V1 exit criteria are unmet.
6. **No persistence boundary.** Roadmap V0 lists in-memory persistence interfaces; none exist.
7. **Duplicate-operation fault** is listed in the product definition and requested for this work,
   but has no `FaultType`.
8. **Seed has no effect.** `ExperimentSpec.seed` and `ExecutionContext.seed` are carried around but
   nothing consumes them. Fault selection is deterministic because it is keyed by invocation number,
   not because of seeded randomness. The documentation's "seeded" language overstates this.
9. **Scenario initial state is disconnected.** `ScenarioSpec.initial_state` is free-form JSON while
   the sandbox hard-codes its fixture in `reset()`. Nothing checks they agree.
10. **Core `StateSnapshot` is unused.** The commerce sandbox returns a typed `CommerceSnapshot`;
    nothing converts it into the core evidence model.
11. **No CI, no type checker, no coverage reporting.**
12. **Web app** is a README placeholder (correctly documented as deferred).

## 4. Design flaws and risks

| # | Finding | Risk | Recommendation |
| --- | --- | --- | --- |
| D1 | `ExperimentRunResult.outcome` is caller-supplied and never checked against `invariant_results`. A result can say `PASS` with failing invariants. | Evaluation-correctness: the one thing RIFT must not get wrong. | Derive outcome in one place (runner) from invariant results; test it. |
| D2 | `AmbiguousToolOutcomeError` subclasses `InjectedTimeoutError` (good) but exposes `operation_may_have_completed = True` on the instance. If an adapter forwarded raw exceptions to an agent, the agent would get an oracle that real systems never provide. | Experiments would overstate agent robustness. | The tool gateway must normalize both timeouts to an identical caller-visible `timeout` result. Test the indistinguishability. |
| D3 | `ScenarioSpec.invariant_ids` and `tool_names` are not checked against the invariants and tools a scenario actually provides. | Silent drift between declared and evaluated checks. | Validate at runner start; fail fast with a typed error. |
| D4 | A fault rule targeting an invocation the agent never makes is silently inert. The faulted run then passes and looks "resilient". | False confidence — a classic chaos-testing mistake. | Report unfired rules; a faulted run with zero injected faults gets an `inconclusive` comparison. |
| D5 | Invocation records have no run-global sequence number, only a per-tool counter. Ordering across tools relies on recorder list order. | Trace ordering is implicit. | Acceptable for the in-process runner (recorder order is completion order); document it and add an explicit index in reports. |
| D6 | All packages ship as one distribution (`rift`). Dependency rules are enforced only by convention plus one AST test for the invariant engine. | Boundaries erode silently. | Extend the AST boundary test to every package. Splitting distributions is not justified yet. |
| D7 | Executor records successful calls with `underlying_operation_committed=None` even for the in-memory sandbox where commit is certain. | None — this is the honest default. | Keep. Explain in docs why `None` is correct at a generic boundary. |
| D8 | Executor counters and the default recorder grow unboundedly across runs on one instance. | Minor memory growth in long processes. | Runner creates one executor per run. |

## 5. Documentation accuracy

| Location | Problem |
| --- | --- |
| `README.md` line 8 | "The only runtime behavior currently implemented is an API health endpoint" contradicts the "Current scope" list directly below it. |
| `docs/domain-model.md` (`FaultType`) | "These are model semantics only; no executor is implemented yet" — stale since `b179de9`. |
| `docs/product.md` | First demo described as "not functionality included in the current repository" — partially stale (sandbox and invariants exist). |
| `examples/commerce_demo/README.md` | Says the example has no invariant evaluation — stale with the uncommitted work. |
| Multiple docs | "Seeded" fault selection is claimed; the seed is unused (finding 3.8). |

## 6. Test coverage gaps

- No test exercises a complete baseline → faulted → compare lifecycle.
- No test proves reset isolation between baseline and faulted runs through a runner.
- No test proves outcome is independent of the agent's final message *at the run level* (only at
  the invariant level).
- No test for an invalid baseline, an unfired fault rule, or a crashing adapter.
- No test that the two timeout kinds are indistinguishable to an agent.
- No reproducibility test across repeated runs (same inputs → same RIFT-controlled decisions).
- Dependency-boundary test covers only the invariant engine.

## 7. Security, reliability, maintainability

- No secrets in the repository; `.env` is ignored; settings use a `RIFT_` prefix. Good.
- `Settings` reads `.env` from the current directory — acceptable for local use; document it.
- Invocation records persist raw tool arguments. Fine for synthetic data; real integrations will need
  the redaction policy already noted in the architecture (V3).
- The Dockerfile runs as root and installs without the lock file. Low priority for a local tool.

## 8. Prioritized backlog

Priority reflects dependency order and value to the product's core claim. Status is updated in
`docs/progress-log.md`.

| ID | Pri | Item | Roadmap |
| --- | --- | --- | --- |
| B1 | P0 | Agent adapter contract, tool gateway with caller-visible error normalization, scripted adapter | V0 |
| B2 | P0 | Experiment runner: reset → baseline → faulted → evaluate → compare; outcome derivation; invalid-baseline and unfired-rule handling | V0 |
| B3 | P0 | Commerce scenario binding (tools + invariants) and scripted agent profiles (naive, retrying, idempotent, reconciling) | V1 |
| B4 | P0 | CLI (`rift demo`, `rift run`, `rift list`) with human-readable and JSON reports | V1 |
| B5 | P0 | End-to-end tests: recovery, failed recovery, partial completion, timeout-after-commit, idempotency, duplicate prevention, reproducibility | V1 |
| B6 | P1 | `DUPLICATE_REQUEST` fault type (at-least-once delivery) | V1 |
| B7 | P1 | Fix stale documentation; README implemented-vs-planned table; demo walkthrough | V1 |
| B8 | P1 | CI workflow (ruff, format, mypy, pytest); mypy configuration | V5 (pulled forward: cheap, high value) |
| B9 | P1 | Boundary test for every package | V0 |
| B10 | P2 | Multi-seed / probabilistic rules with stateless hash-based selection; fault-matrix runs | V1+ |
| B11 | P2 | Experiment definition files (JSON) loaded by the CLI | V1 |
| B12 | P2 | In-memory then SQLite persistence behind a repository interface | V0/V2 |
| B13 | P2 | API endpoints to list scenarios/agents/faults, run experiments, fetch reports | V2 |
| B14 | P3 | Web dashboard (only after B13; must show traces, invariant evidence and comparisons) | V2 |
| B15 | P3 | One real framework adapter (e.g. OpenAI Agents SDK or LangGraph) as an optional extra, excluded from the default test suite | post-V1 |
| B16 | P3 | Evidence export bundle (spec + traces + snapshots + results, content-hashed) | V2 |

### Improvements evaluated and deferred

- **Resilience score.** A single number hides *which* invariant broke. RIFT already reports an
  unweighted pass ratio; a weighted score adds opinion without information. Deferred; prefer the
  fault × agent matrix.
- **Property-based testing (Hypothesis).** Valuable for the executor and sandbox (e.g. "any
  sequence of idempotent refund calls with one key creates at most one refund"). Worth adding as a
  test-only dependency once the core is stable (P2).
- **Failure categorization.** High value and cheap: classify each run by *agent claim × actual
  state* (silent failure vs. detected failure). Included in B2.
- **Temporal, Kubernetes, OpenTelemetry, PostgreSQL.** No demonstrated need; remain on the roadmap
  as documented.

## 9. Status after Milestone 1 (2026-11-01)

"Verified" means a test or command proves it against this checkout. Evidence is in
[milestone-1-closeout.md](milestone-1-closeout.md).

| Finding | Status | Evidence |
| --- | --- | --- |
| 3.1 No experiment runner | Resolved, verified | `test_experiment_lifecycle.py`, `test_commerce_experiments_e2e.py` |
| 3.2 No adapter contract / scripted adapter | Resolved, verified | `test_scripted_adapter.py` |
| 3.3 No tool gateway | Resolved, verified | `test_tool_gateway.py` (timeout kinds indistinguishable) |
| 3.4 No comparison / invalid baseline / unfired rules | Resolved, verified | lifecycle and reliability-limit tests |
| 3.5 No CLI or report | Resolved, verified | `test_cli.py`, `docs/samples/` |
| 3.6 No persistence | Open | — |
| 3.7 No duplicate-operation fault | Resolved, verified | `DUPLICATE_REQUEST` executor, domain and E2E tests |
| 3.8 Seed unused | Open, documented | B10 |
| 3.9 Initial state disconnected | Partly resolved | Runner checks reset state against declared state, but the commerce declaration is self-derived (M1-D3) |
| 3.10 Core `StateSnapshot` unused | Resolved, verified | Runner stores the final state as a `StateSnapshot` |
| 3.11 No CI / type checker | Partly resolved | mypy strict verified locally; CI workflow written but **unverified** |
| D1 Outcome caller-settable | Mitigated | Runner derives it (`test_runner_evaluation.py`); the core model still accepts any value (M1-D1) |
| D2 Ambiguity oracle leak | Mitigated, verified at the gateway | M1-D5 remains for direct executor users |
| D3 Declared tools/invariants unchecked | Resolved, verified | `ExperimentConfigurationError` tests |
| D4 Inert fault rules | Resolved, verified | `not_exercised` verdict tests |
| D5 No global sequence | Open, tested as a limitation | `test_concurrent_invocations_are_numbered_by_start_and_recorded_by_completion` (M1-D2) |
| D6 Boundary test partial | Resolved, verified | Parametrized over all five packages, original test kept |
| D8 Unbounded executor state | Resolved by design | One executor per run |
| §5 Stale documentation | Resolved | Replaced sentences listed in the closeout |
| Python 3.11 support | **Unverified** | Interpreter not installed; static checks only |
| Docker image | **Unverified** | Engine not running; static `COPY` checks only |

New findings from the closeout: M1-D3 (circular fixture declaration) and M1-D4 (no ordering
invariant). M1-D4 was demonstrated with a scripted agent that refunds, confirms and restores
before cancelling; its baseline outcome is `pass`.

## 10. Status after Milestone 2 (2026-11-01)

Details and before/after evidence: [milestone-2-evidence-hardening.md](milestone-2-evidence-hardening.md).

| Defect | Status | Evidence (local unless stated) |
| --- | --- | --- |
| M1-D3 Circular starting-state check | Fixed, verified | `tests/test_starting_state.py`: 3 tests failed before the fix ("DID NOT RAISE", missing fixture) and pass after |
| M1-D4 No ordering invariant | Fixed, verified | `tests/test_ordering_invariant.py`: the refund-first agent passed before and fails now; independent oracle rule R6 agrees in all 80 runs |
| M1-D1 Outcome caller-settable | Fixed, verified | `tests/test_run_result_validation.py`: core accepted `PASS` with a failing invariant before; rejects it now |
| M1-D2 No run-global sequence | Fixed, verified | `tests/test_invocation_sequencing.py`: overlapping-call ordering violation passed before and fails now |
| M1-D7 Dockerfile unpinned and root | Fixed; **image build unverified** | `tests/test_dockerfile.py` (static policy; flags all four defects in the old file); `uv sync --locked` steps replayed in a clean directory; real build runs only in the CI `docker` job |
| M1-D5 Executor exception leaks commit status | Open (not in Milestone 2 scope) | Gateway still mitigates |
| M1-D6 Throwaway environment in `_validate` | Open (not in Milestone 2 scope) | — |
| CI on 3.11 / 3.12 | Workflow written; `check` steps replayed locally on **3.12 (Windows)** only | GitHub run requires a push |
| Python 3.11 runtime | **Unverified** | Not installed locally |
