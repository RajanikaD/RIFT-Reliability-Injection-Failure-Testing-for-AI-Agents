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

## 2026-11-01 — Milestone 2: evidence hardening

Each defect was first reproduced by a failing test, then fixed. Snapshots of the tree after each
step back the [commit plan](commit-plan.md).

| Step | Failing first | Fix | Verified |
| --- | --- | --- | --- |
| D3 | drifted fixture and mismatched spec both ran ("DID NOT RAISE") | checked-in `fixtures/initial_state.json`; runner checks the experiment's declaration and full scenario equality | 4 tests; full suite 180 passed |
| D4 | refund-first agent's baseline was `pass` | trace evidence passed to invariants; `refund_after_cancellation`; scenario v2 | 5 tests; oracle R6; 185 passed |
| D1 | core accepted `PASS` with a failing invariant | `derive_run_outcome` in core; `ExperimentRunResult` validates | 10 tests; 195 passed |
| D2 | overlapping cancel/refund judged correctly ordered | `sequence_number`, `completed_before_start`; happens-before ordering | 4 tests; 199 passed |
| D7 | old Dockerfile: 4 policy violations | `uv sync --locked`, non-editable, UID 10001, healthcheck; CI docker job | 2 static tests; locked sync replayed in clean dir |

- **Verified locally:** 201 passed; ruff, format and strict mypy clean (37 files); every CI `check`
  step replayed in a clean copy on Python 3.12 (Windows); wheel contains the fixture.
- **Not verified:** GitHub Actions (needs a push), Python 3.11, the Docker image build and the CI
  `docker` job (no engine).

## 2026-11-01 — Integration preparation (no commits yet)

- **Changed:** the commit plan moves the ordering invariant's message and evidence change from
  the docs commit into the D2 commit. Machine-specific paths were generalized in the audit,
  closeout and plan. `.mypy_cache/` was added to `.gitignore`. Commit messages state provenance.
- **Verified locally:** the integration script was rehearsed in a scratch repository. All 8
  commits pass the full gate (80 → 201 tests), and the working tree after commit 8 is clean.
  None of the 113 introduced blobs contain secrets, artifacts or machine paths. Push credentials
  and `safe.directory` propagation were checked with `git push --dry-run` (nothing created).
- **Pending approval:** creating the commits, pushing `feature/evidence-hardening`, and opening a
  draft PR (required for CI to run).

## 2026-11-02 — Repository integration and GitHub CI verification

- **Integrated:** eight commits on `feature/evidence-hardening` (`ac3088c` … `daa7d62`) on base
  `677ab21`. They were pushed normally and opened as draft PR #1 against `main`; `main` is
  unchanged. Commit 1 is the pre-existing invariant-engine work, committed unchanged.
- **Verified in GitHub Actions** (run
  [`41390815914`](https://github.com/RajanikaD/RIFT-Reliability-Injection-Failure-Testing-for-AI-Agents/actions/runs/41390815914),
  Ubuntu; all jobs succeeded):
  - Python 3.11.15 and 3.12.13: locked install, ruff, format, strict mypy, **201 passed** on each,
    demo smoke test, sdist and wheel built, fixture present in the wheel.
  - Docker: image built with `uv sync --locked`; runs as UID **10001**; `/health` returned
    `{"status":"ok","service":"rift-api"}`; the CLI in the container returned `RESILIENT`.
- **Still not verified:** a local Docker engine build. **Non-blocking notices:** GitHub Actions
  Node 20 deprecation for `actions/checkout@v4` and `astral-sh/setup-uv@v6`; `useradd` UID above
  `SYS_UID_MAX`. No code was changed for these.
- **Earlier entries** above are kept as written; they record what was verified at the time.

## 2026-11-07 — Commit references

- **Changed:** commit messages from the invariant-engine commit onward were updated on `main` and
  `feature/evidence-hardening`, which changed their hashes. Source trees, authors, committers,
  dates and merge structure are unchanged. The merge commit no longer carries GitHub's signature.
- **Evidence:** CI evidence above is identified by run number. Those runs tested the earlier
  commits, whose source trees are identical to the current ones.

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
| B8 | CI and mypy | Done; verified in GitHub Actions run 41390815914 (3.11 and 3.12) |
| B9 | Boundary test for every package | Done |
| B10 | Seeded probabilistic rules, multi-seed runs | After Milestone 2 |
| B11 | Experiment JSON files via CLI | Done (`--spec`) |
| B12 | Persistence (in-memory → SQLite) | Open |
| B13 | Experiment API | Open |
| B14 | Web dashboard | Open (after B13) |
| B15 | Real framework adapter (optional extra) | Open |
| B16 | Evidence export bundle | Partly (`--json` report) |
| M2-1 | Commit (with approval), push branch, CI green on 3.11/3.12 | Done: draft PR #1; CI green in run 41390815914; merge awaits approval |
| M2-2 | Docker build verified; lock-based install; non-root user (M1-D7) | Done; verified in CI run 41390815914 (local engine build not run) |
| M2-3 | Validate outcome against invariant results in `rift_core` (M1-D1) | Done, verified |
| M2-4 | Checked-in commerce initial-state fixture (M1-D3) | Done, verified |
| M2-5 | Run-global invocation `sequence_number` (M1-D2) | Done, verified (plus `completed_before_start`, see ADR-006) |
| M2-6 | Trace-aware ordering invariant (M1-D4) | Done, verified |
| M3-1 | M1-D5: stop exposing commit status on executor exceptions to direct callers | Open |
| M3-2 | M1-D6: validate tool bindings without building an environment | Open |
