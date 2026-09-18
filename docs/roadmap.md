# Roadmap

The roadmap is ordered to validate local semantics before adding user-interface, telemetry, and distributed-execution complexity. A version begins only after the prior version's exit criteria are met or an ADR records a deliberate change.

## V0 — Core engine

Goal: establish a deterministic, framework-agnostic engine with unit-tested domain behavior.

Planned scope:

- Repository and packaging scaffold, including a bootstrap-only FastAPI health endpoint.
- Python project structure for `rift_core`, `fault_engine`, `experiment_runner`, `agent_adapters`, `sandbox`, `invariant_engine`, and `persistence`.
- Typed domain models and component contracts from the domain model.
- Deterministic run-scoped randomness and ordered rule matching.
- A minimal subset of fault types sufficient to validate interception semantics.
- In-memory persistence interfaces and implementation.
- `ScriptedAgentAdapter` test double for deterministic action sequences.
- Unit tests for rule matching, seed reproducibility, before/after-execution semantics, invariant aggregation, and run sequencing.
- ADRs for any material decisions not covered by the initial records.

Exit criteria:

- A test-only scenario can execute baseline and faulted runs in process.
- The same configuration and seed produce the same RIFT-controlled decisions.
- Tests prove that outcome evaluation does not depend on agent response text.

Intentionally excluded: experiment-facing FastAPI endpoints, ecommerce demo behavior, Next.js, PostgreSQL, external model APIs, OpenTelemetry, and Temporal.

## V1 — Local working demo

Goal: demonstrate an end-to-end experiment against a resettable ecommerce sandbox.

Planned scope:

- Synthetic ecommerce state and tools for order cancellation, refunding, inventory restoration, and confirmation.
- Scenario for order `ORD-1001` and its outcome invariants.
- Local command-line entry point for running an experiment and viewing a comparison.
- A documented set of fault cases, including ambiguous post-commit failure and duplicate-risk behavior.
- Human-readable report derived from structured results.
- Integration tests for baseline reset isolation, successful recovery, partial failure, idempotency, and duplicate prevention.

Exit criteria:

- The demo runs without paid APIs or network access.
- Baseline and faulted runs start from equivalent fixtures.
- Reports identify invariant failures with state evidence and affected invocations.

Intentionally excluded: browser UI, hosted services, production integrations, and distributed execution.

## V2 — Web application

Goal: make local experiments configurable and inspectable through a web interface.

Planned scope:

- FastAPI application layer and versioned HTTP contracts.
- Next.js, TypeScript, and Tailwind UI for experiment definitions, run history, traces, snapshots, and comparisons.
- SQLAlchemy persistence with PostgreSQL as the target database.
- Local development configuration and database migrations.
- Validation, pagination, error handling, and secret-safe configuration.
- API and browser-level tests for primary workflows.

Exit criteria:

- A user can define or select the demo experiment, run it, and inspect evidence in the UI.
- Restarting the application preserves definitions and finalized results.
- Core and adapter boundaries remain independent of FastAPI, SQLAlchemy, and Next.js.

Intentionally excluded: multi-tenant hosting, enterprise authentication, and durable workflow execution.

## V3 — Observability

Goal: expose standardized diagnostic signals without changing evaluation semantics.

Planned scope:

- OpenTelemetry traces and metrics for experiment, run, adapter, and tool-invocation lifecycles.
- Correlation between telemetry and persisted RIFT identifiers.
- Configurable redaction and payload-capture policy.
- Optional Langfuse exporter behind an observability interface.
- Documentation and tests for exporter failure isolation.

Exit criteria:

- A local run can be inspected through standard telemetry tooling.
- Disabling or losing an exporter does not change run outcomes.
- Sensitive fields are excluded or redacted according to configuration.

Intentionally excluded: making telemetry backends authoritative stores for RIFT results.

## V4 — Durable execution

Goal: make long-running experiments resumable and operationally robust after local orchestration semantics are stable.

Planned scope:

- Temporal workflows and activities wrapping existing runner operations.
- Explicit retry, cancellation, timeout, and idempotency policies.
- Recovery tests for worker interruption and process restart.
- Versioning strategy for in-flight workflows.
- Deployment guidance for workers and the API.

Exit criteria:

- Interrupted experiments resume without silently duplicating finalized run artifacts.
- Workflow replay is deterministic.
- Temporal-specific code coordinates core services without owning fault or invariant logic.

Intentionally excluded: arbitrary production-system chaos injection and unbounded workflow scale claims.

## V5 — Public portfolio release

Goal: publish a reproducible, reviewable open-source project suitable for external use and technical evaluation.

Planned scope:

- Stable setup, contribution, security, and architecture documentation.
- License, code of conduct, issue templates, and release process.
- Automated linting, type checking, tests, dependency review, and build verification.
- Reproducible demo data and a concise walkthrough.
- Deployment reference for the web application, API, and PostgreSQL.
- Public API compatibility policy and documented limitations.
- Clean-room and third-party license review.

Exit criteria:

- A new contributor can set up and run the tested demo from public instructions.
- Continuous integration passes from a clean checkout.
- The repository contains no secrets, private artifacts, or undocumented required services.
- Release notes state supported adapters, fault types, and known limitations.
