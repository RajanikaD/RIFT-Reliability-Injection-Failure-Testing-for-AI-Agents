# ADR-001: Keep the core agent-framework agnostic

- Status: Accepted
- Date: 2026-09-18

## Context

RIFT must test agents implemented with different frameworks and provider SDKs. Coupling fault selection, run orchestration, or evaluation to one framework would make experiment behavior difficult to reuse and would allow provider-specific types to shape the domain model.

The project expects an OpenAI Agents SDK integration, but that integration is one execution mechanism rather than the definition of RIFT.

## Decision

The RIFT core will not depend on OpenAI, LangChain, LangGraph, or another agent framework or model provider.

Agent implementations integrate through the framework-neutral `AgentAdapter` contract. Provider-specific packages, configuration translation, tool registration, exceptions, and result normalization remain inside the corresponding adapter package. The experiment runner supplies an adapter with a scenario execution context and an intercepted tool boundary; it consumes only normalized results.

Shared contracts and domain types live in `rift_core`. Dependencies point inward toward those contracts. No provider SDK object may appear in a core public interface or persisted domain record.

## Consequences

### Positive

- Experiments and invariant evaluation can be reused across agent frameworks.
- The core can be tested without network calls, model credentials, or provider packages.
- Provider SDK upgrades are isolated to adapters.
- Framework behavior can be compared without redefining fault semantics.

### Negative

- Adapters must translate framework-native capabilities into a smaller common contract.
- Some provider-specific diagnostic data will require optional normalized metadata or adapter-owned extensions.
- Maintaining multiple adapters adds compatibility testing work.

## Guardrails

- Core package tests must run without provider SDKs installed.
- Adapter dependencies must be optional from the core package's perspective.
- Adding a provider-specific field to a shared model requires a new ADR or an update to this decision.

## Alternatives considered

### Build directly on the OpenAI Agents SDK

Rejected because it would accelerate one integration at the cost of making core orchestration and tool interception provider-specific.

### Define separate experiment engines per framework

Rejected because fault semantics, result comparison, and invariants would diverge and become difficult to compare.

