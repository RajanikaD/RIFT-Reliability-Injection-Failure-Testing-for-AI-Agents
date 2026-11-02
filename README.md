# RIFT

RIFT (Reliability Injection & Failure Testing for AI Agents) tests whether tool-using AI agents
reach correct system outcomes when their tools and dependencies fail.

It injects deterministic faults at the tool boundary, runs the agent against a resettable
sandbox, and evaluates the **actual resulting state** with executable invariants. A run passes
only when the invariants hold — for example: the order is cancelled, exactly one correctly sized
refund exists, inventory is restored once, and exactly one confirmation was sent. What the agent
*says* happened is recorded and compared against what demonstrably happened, but never trusted.

## Design goals

- Keep the fault-injection core independent of agent frameworks and model providers.
- Integrate agent frameworks through explicit adapters.
- Make fault selection and execution reproducible from configuration and a random seed.
- Evaluate persisted outcomes and side effects with executable invariants.
- Keep orchestration, injection, execution, state, evaluation, and observability separate.
- Establish a local, deterministic vertical slice before adding distributed infrastructure.
- Record major architectural decisions in `docs/adr/`.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) (or plain `pip`).

```bash
uv sync --extra dev
uv run rift demo
```

Without uv: `python -m venv .venv`, activate it, then `pip install -e ".[dev]"` and run `rift demo`.
No network access, API keys or paid services are needed.

### Expected demo output

Every agent profile is run against every fault case (36 baseline-vs-faulted experiments). Each cell
is the faulted run's classification:

```text
                                   naive               retrying            idempotent          reconciling
refund-timeout-after-commit        correct             silent_failure      correct             correct
refund-timeout-before-call         silent_failure      correct             correct             correct
refund-rate-limited                silent_failure      correct             correct             correct
refund-outage                      silent_failure      detected_failure    detected_failure    detected_failure
refund-malformed-response          correct             silent_failure      correct             correct
refund-duplicate-request           silent_failure      silent_failure      correct             correct
inventory-timeout-after-commit     correct             silent_failure      silent_failure      correct
confirmation-timeout-after-commit  correct             silent_failure      correct             correct
cancel-latency                     correct             correct             correct             correct
```

How to read it:

- **Retrying is not the same as recovering.** The `retrying` agent survives timeouts *before*
  execution but duplicates refunds and notifications after a timeout *after commit*, and still
  reports success (`silent_failure`).
- **Idempotency keys only help where the API supports them.** The `idempotent` agent is safe for
  refunds and confirmations but double-restores inventory, whose API has no key.
- **Reconciliation closes the gap.** The `reconciling` agent reads inventory before retrying and
  is correct in every recoverable case. Under a persistent outage it fails *honestly*
  (`detected_failure`) instead of claiming success.
- **Naive can look fine by luck.** Ignoring a timeout-after-commit happens to leave correct state;
  the same agent silently fails when the operation really did not run.

Inspect one experiment in detail, including trace, invariant evidence and state diff:

```bash
uv run rift run --agent retrying --fault refund-timeout-after-commit
```

```text
VERDICT: DEGRADED
  Faults were injected and the faulted run ended fail; invariants not satisfied: exactly_one_refund, refund_amount_correct. The agent nevertheless reported success.
...
FAULTED run  outcome=fail  invariants=4/6  agent=completed  classification=silent_failure
  trace (completion order; seq = start order):
     1. seq 1   cancel_order#1                                 actual: executed           caller saw success
     2. seq 2   refund_payment#1       [timeout_after_commit]  actual: executed           caller saw error
     3. seq 3   refund_payment#2                               actual: executed           caller saw success
...
State differences (baseline vs faulted final state)
  + refunds[1] = {"amount": "79.99", "idempotency_key": null, "payment_id": "PAY-1001", ...}
```

Other commands: `rift list` (agents and fault cases), `rift run --json report.json`,
`rift run --spec experiment.json` (an `ExperimentSpec` JSON file), and `rift run --strict`
(exit code 1 unless the verdict is `resilient`, for use in CI).

## What is implemented

| Capability | Status |
| --- | --- |
| Framework-neutral domain model (`rift_core`) | Implemented |
| Fault executor: latency, exception, rate limit, timeout-before-call, timeout-after-commit, malformed response, duplicate request | Implemented |
| Agent adapter contract and tool gateway that hides fault provenance from agents | Implemented |
| `ScriptedAgentAdapter` with retry, validation and state reconciliation | Implemented |
| Deterministic commerce sandbox with request idempotency | Implemented |
| Invariant engine; five state invariants plus a trace-aware ordering invariant (refund only after cancellation) | Implemented |
| Experiment runner: reset → baseline → faulted → evaluate → compare; starting state verified against a checked-in fixture | Implemented |
| Agent-claim vs. actual-state classification; invalid-baseline and unfired-fault detection | Implemented |
| CLI with text and JSON reports; reproducibility fingerprints; run-global invocation sequence and happens-before evidence | Implemented |
| Run outcome validated against invariant results in `rift_core` | Implemented |
| CI workflow: lint, format, strict mypy, tests, demo, build on 3.11 and 3.12; Docker build, non-root, `/health`, CLI | Written; steps replayed locally on 3.12; **not yet run on GitHub** |
| API | `GET /health` only |
| Seeded probabilistic faults, multi-seed runs | Planned (seed recorded, not consumed) |
| Persistence, experiment API, web dashboard | Planned (V2) |
| Real LLM framework adapter | Planned, optional extra |
| OpenTelemetry, Temporal | Roadmap V3/V4, not justified yet |

## Architecture

```text
rift_cli ──► rift_experiment_runner ──► rift_fault_engine ──► rift_core
                 │            │                                  ▲
                 │            └──► rift_invariant_engine ────────┤
                 ▼                                               │
   AgentAdapter (rift_agent_adapters) ── ToolGateway ────────────┘
   ScenarioBinding (commerce_demo: sandbox, tools, invariants, agents, fault cases)
```

Agent → `ToolGateway` → `FaultInjectingToolExecutor` → scenario tool → sandbox state. The runner
snapshots state before and after, evaluates invariants, and compares baseline with faulted runs.
Dependency rules are enforced by an AST-based test. See
[architecture](docs/architecture.md), [experiment runner](docs/experiment-runner.md),
[fault execution](docs/fault-execution.md), and the [ADRs](docs/adr/).

## System boundaries

| Boundary | Package | Responsibility | Status |
| --- | --- | --- | --- |
| `rift_core` | `rift_core` | Shared domain types, contracts, identifiers, and result models | Implemented |
| `fault_engine` | `rift_fault_engine` | Deterministic fault injection at tool boundaries | Implemented |
| `experiment_runner` | `rift_experiment_runner` | Baseline/faulted run orchestration and comparison | Implemented |
| `agent_adapters` | `rift_agent_adapters` | Agent execution behind a common interface | Scripted adapter only |
| `sandbox` | `commerce_demo` | Resettable test environment, tools, and state inspection | Implemented (commerce) |
| `invariant_engine` | `rift_invariant_engine` | Outcome-based invariant evaluation | Implemented |
| `persistence` | — | Storage interfaces and implementations | Planned |
| `api` | `rift_api` | FastAPI transport | Health check only |
| `web` | — | Next.js user interface | Planned |

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

The API health endpoint: `uv run uvicorn rift_api.main:app --reload`, then
`http://127.0.0.1:8000/health`. Copy `.env.example` to `.env` only for local overrides; `.env` is
ignored by Git.

Build and run the API container from the repository root. The image installs strictly from
`uv.lock` and runs as an unprivileged user. Its build has not been run locally (no Docker engine
was available); the CI `docker` job builds and smoke-tests it. See
[Milestone 2](docs/milestone-2-evidence-hardening.md).

```bash
docker build -f apps/api/Dockerfile -t rift-api .
docker run --rm -p 8000:8000 rift-api
```

## Documentation

- [Implementation audit and backlog](docs/implementation-audit.md)
- [Progress log](docs/progress-log.md)
- [Milestone 1 closeout](docs/milestone-1-closeout.md) · [Milestone 2: evidence hardening](docs/milestone-2-evidence-hardening.md) · [Commit plan](docs/commit-plan.md)
- [Product definition](docs/product.md) · [Roadmap](docs/roadmap.md)
- [Architecture](docs/architecture.md) · [Domain model](docs/domain-model.md)
- [Fault execution](docs/fault-execution.md) · [Experiment runner](docs/experiment-runner.md)
- [Commerce sandbox](docs/commerce-sandbox.md) · [Invariant evaluation](docs/invariant-evaluation.md)
- [Architecture decision records](docs/adr/)

## Clean-room development

RIFT is independently designed from public documentation and uses synthetic data only.
Contributions must not copy private or proprietary code, schemas, prompts, documentation, naming
systems, or architecture.
