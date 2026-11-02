# Progress log

Concise, verified record of each milestone. "Verified" means the listed command was run and passed.

## 2026-11-01 — Milestone 1: audit and baseline

- **Changed:** added `docs/implementation-audit.md` (findings and prioritized backlog B1–B16).
- **Why:** establish what exists before building on it.
- **Verified:** `pytest` 80 passed; `ruff check`, `ruff format --check` clean.
- **Discovered:** the local `.venv` imported source from a different checkout; rebuilt it (see audit §1).

## 2026-11-01 — Milestone 2: end-to-end experiment slice (B1–B9, B11)

- **Changed:**
  - `rift_core.contracts`: `AgentAdapter`, `ToolGateway`, `ToolCallOutcome`, `ToolErrorKind`,
    `ToolSpec`, `AgentTask`, `AgentRunOutput`, `AgentStatus`.
  - `FaultType.DUPLICATE_REQUEST` and `ToolInvocation.underlying_execution_count`.
  - New `rift_agent_adapters` (`ScriptedAgentAdapter`) and `rift_experiment_runner` (runner,
    gateway, evaluation rules, report models, text renderer).
  - Commerce: `get_inventory`/`list_refunds` read operations, tool bindings, scenario binding,
    four agent profiles, ten fault cases.
  - `rift` CLI (`list`, `run`, `demo`, `--json`, `--spec`, `--strict`).
  - Strict mypy config, CI workflow, AST boundary test for all packages, ADR-005, docs.
- **Why:** the runner, adapter and comparison were the product's missing core (audit §3.1–3.5).
- **Verified:** `pytest` 157 passed; `ruff check`/`format --check` clean; `mypy` (strict, 35
  files) clean; `uv lock --check` consistent; `rift demo` output matches the README. Mutation
  spot-checks: leaking timeout provenance in the gateway and removing the not-exercised rule each
  made the corresponding test fail.
- **Not verified:** the GitHub Actions workflow has not run (nothing pushed); Python 3.11 was not
  run locally (only 3.12.14); the Docker image was not rebuilt.
- **Demo:** `uv run rift demo`, then `uv run rift run --agent retrying --fault refund-timeout-after-commit`.

## 2026-11-01 — Milestone 1 closeout

- **Changed:** diff provenance review; restored the original boundary test and README sections my
  earlier edits had removed; added `test_business_oracle.py` (independent rules R1–R5 and
  trace↔state rules C1–C6 over all 40 agent × fault experiments) and
  `test_reliability_limits.py` (concurrency, ambiguous commits, invalid baselines, never-fired
  faults, cross-process reproducibility); added `docs/milestone-1-closeout.md` and
  `docs/samples/`.
- **Verified:** 176 passed (editable install); 176 passed against the built wheel in a clean venv;
  ruff, format and strict mypy clean; `uv lock --check` consistent; static Docker `COPY` checks.
  The oracle detected a planted invariant bug.
- **Not verified:** Python 3.11 (not installed), Docker build (engine stopped), CI (not pushed).
- **Found:** M1-D1 to M1-D7 (see closeout §4). The reconciling strategy misattributes concurrent
  writes; a test pins this as a documented limitation.

## Backlog status

| ID | Item | Status |
| --- | --- | --- |
| B1 | Adapter contract, gateway, scripted adapter | Done |
| B2 | Experiment runner, outcome derivation, comparison | Done |
| B3 | Commerce binding and agent profiles | Done |
| B4 | CLI and reports | Done |
| B5 | E2E proofs (recovery, failed recovery, partial, after-commit, idempotency, duplicates, reproducibility) | Done |
| B6 | `DUPLICATE_REQUEST` fault | Done |
| B7 | Stale docs, README implemented-vs-planned | Done |
| B8 | CI and mypy | mypy verified; CI workflow unverified |
| B9 | Boundary test for every package | Done |
| B10 | Seeded probabilistic rules, multi-seed runs | After Milestone 2 |
| B11 | Experiment JSON files via CLI | Done (`--spec`) |
| B12 | Persistence (in-memory → SQLite) | Open |
| B13 | Experiment API | Open |
| B14 | Web dashboard | Open (after B13) |
| B15 | Real framework adapter (optional extra) | Open |
| B16 | Evidence export bundle | Partly (`--json` report) |
| M2-1 | Commit (with approval), push branch, CI green on 3.11/3.12 | Next — needs approval |
| M2-2 | Docker build verified; lock-based install; non-root user (M1-D7) | Next |
| M2-3 | Validate outcome against invariant results in `rift_core` (M1-D1) | Next |
| M2-4 | Checked-in commerce initial-state fixture (M1-D3) | Next |
| M2-5 | Run-global invocation `sequence_number` (M1-D2) | Next |
| M2-6 | Trace-aware ordering invariant (M1-D4) | Next |
