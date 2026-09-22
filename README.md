# RIFT

RIFT (Reliability Injection & Failure Testing for AI Agents) is an open-source engineering project for testing whether tool-using AI agents reach correct system outcomes when their tools and dependencies fail.

RIFT evaluates observable state rather than relying on an agent's final message. A run succeeds only when its declared invariants hold—for example, an order is cancelled, exactly one correctly sized refund exists, inventory is restored, and no duplicate confirmation is sent.

This repository contains the initial engineering blueprint and a minimal Python scaffold. The only runtime behavior currently implemented is an API health endpoint.

## Design goals

- Keep the fault-injection core independent of agent frameworks and model providers.
- Integrate agent frameworks through explicit adapters.
- Make fault selection and execution reproducible from configuration and a random seed.
- Evaluate persisted outcomes and side effects with executable invariants.
- Keep orchestration, injection, execution, state, evaluation, and observability separate.
- Establish a local, deterministic vertical slice before adding distributed infrastructure.
- Record major architectural decisions in `docs/adr/`.

## Current scope

The scaffold provides:

- Python packaging for the API and future framework-agnostic core.
- Framework-agnostic experiment, scenario, fault-rule, and run-evidence models.
- Deterministic direct and fault-injecting async tool executors.
- Environment-backed API configuration.
- `GET /health` in FastAPI.
- pytest and Ruff configuration.
- A minimal API Dockerfile.

Experiment orchestration, agent adapters, sandbox behavior, invariant evaluation, persistence, and web functionality are not implemented.

A later local demo will simulate an ecommerce support request:

> Cancel order ORD-1001, refund the customer, restore inventory, and send confirmation.

The demo will compare a fault-free baseline with faulted executions and independently verify the resulting system state. The demo itself is not implemented.

## Backend setup

RIFT requires Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` only when local overrides are needed. `.env` is ignored by Git.

Start the API:

```powershell
uvicorn rift_api.main:app --reload
```

Then request `http://127.0.0.1:8000/health`.

Run tests and linting:

```powershell
pytest
ruff check .
ruff format --check .
```

Build and run the API container from the repository root:

```powershell
docker build -f apps/api/Dockerfile -t rift-api .
docker run --rm -p 8000:8000 rift-api
```

## System boundaries

| Boundary | Responsibility |
| --- | --- |
| `rift_core` | Shared domain types, contracts, identifiers, and result models |
| `fault_engine` | Deterministic fault planning and injection at tool boundaries |
| `experiment_runner` | Baseline/faulted run orchestration and comparison |
| `agent_adapters` | Framework-specific agent execution behind a common interface |
| `sandbox` | Resettable test environment, tools, and state inspection |
| `invariant_engine` | Outcome-based invariant evaluation |
| `persistence` | Storage interfaces and implementations for definitions and results |
| `api` | FastAPI transport and application-facing endpoints |
| `web` | Next.js user interface |

See [the architecture](docs/architecture.md), [domain model](docs/domain-model.md), and [roadmap](docs/roadmap.md) for details.

## Documentation

- [Product definition](docs/product.md)
- [Architecture](docs/architecture.md)
- [Domain model](docs/domain-model.md)
- [Fault execution](docs/fault-execution.md)
- [Roadmap](docs/roadmap.md)
- [Architecture decision records](docs/adr/)

## Project status

Repository scaffold complete. The API health check is implemented; all reliability-testing behavior remains deferred.

## Clean-room development

RIFT is independently designed from the contents of this repository and public documentation. Contributions must not copy private or proprietary code, schemas, prompts, documentation, naming systems, or architecture.
