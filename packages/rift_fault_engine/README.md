# RIFT fault engine

This package implements the framework-neutral async tool-execution boundary. It can execute operations directly or apply one deterministic `FaultRule` before or after an operation while recording `ToolInvocation` evidence.

It does not orchestrate experiments, run agents, evaluate invariants, implement scenario tools, or persist records.

