# RIFT agent adapters

Implementations of the `rift_core.AgentAdapter` contract.

- `ScriptedAgentAdapter` — a deterministic agent driven by a script of tool calls, with explicit
  retry, response-validation, and state-reconciliation rules. It needs no model provider and is
  what the test suite and demo use.

Framework adapters (for example an OpenAI Agents SDK or LangGraph adapter) belong here as optional
extras. Their dependencies must never become requirements of `rift_core` or the runner.
