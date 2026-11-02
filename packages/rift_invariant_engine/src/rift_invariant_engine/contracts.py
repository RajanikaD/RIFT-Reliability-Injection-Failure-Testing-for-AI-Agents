"""Typed contracts for deterministic invariant evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from pydantic import JsonValue

from rift_core import InvariantResult

StateT = TypeVar("StateT")


@dataclass(frozen=True, slots=True)
class InvariantEvaluationContext(Generic[StateT]):
    """Immutable references to the state transition and sanitized run evidence."""

    before_state: StateT
    after_state: StateT
    evidence: Mapping[str, JsonValue] = field(default_factory=dict)


class Invariant(Protocol[StateT]):
    """Framework-neutral contract implemented by deterministic invariants."""

    @property
    def name(self) -> str:
        """Return the stable invariant identifier."""

    @property
    def description(self) -> str:
        """Describe the outcome condition being checked."""

    def evaluate(self, context: InvariantEvaluationContext[StateT]) -> InvariantResult:
        """Evaluate one state transition without mutating its snapshots."""
