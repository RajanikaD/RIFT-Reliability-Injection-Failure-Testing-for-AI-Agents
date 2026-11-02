"""Experiment orchestration: reset, baseline, faulted run, evaluation, comparison."""

from rift_experiment_runner.evaluation import (
    classify,
    compare,
    derive_outcome,
    diff_states,
    fingerprint,
)
from rift_experiment_runner.gateway import ExecutorToolGateway
from rift_experiment_runner.models import (
    AdapterIdentity,
    Comparison,
    ComparisonVerdict,
    ExperimentReport,
    InvariantDelta,
    OutcomeClassification,
    RunReport,
    StateDifference,
)
from rift_experiment_runner.report import render_text
from rift_experiment_runner.runner import (
    ExperimentConfigurationError,
    ExperimentRunner,
    ScenarioBinding,
    ScenarioEnvironment,
)

__all__ = [
    "AdapterIdentity",
    "Comparison",
    "ComparisonVerdict",
    "ExecutorToolGateway",
    "ExperimentConfigurationError",
    "ExperimentReport",
    "ExperimentRunner",
    "InvariantDelta",
    "OutcomeClassification",
    "RunReport",
    "ScenarioBinding",
    "ScenarioEnvironment",
    "StateDifference",
    "classify",
    "compare",
    "derive_outcome",
    "diff_states",
    "fingerprint",
    "render_text",
]
