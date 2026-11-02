"""Baseline-versus-faulted experiment lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Generic, Protocol, TypeVar

from pydantic import JsonValue

from rift_core import (
    AgentAdapter,
    AgentRunOutput,
    AgentStatus,
    AgentTask,
    ExecutionContext,
    ExperimentRunResult,
    ExperimentSpec,
    RunMode,
    ScenarioSpec,
    StateSnapshot,
    ToolHandler,
    ToolSpec,
)
from rift_experiment_runner.evaluation import (
    classify,
    compare,
    derive_outcome,
    diff_states,
    fingerprint,
    fired_rule_ids,
)
from rift_experiment_runner.gateway import ExecutorToolGateway
from rift_experiment_runner.models import AdapterIdentity, ExperimentReport, RunReport
from rift_fault_engine import (
    Clock,
    FaultInjectingToolExecutor,
    InMemoryInvocationRecorder,
    Sleeper,
    SystemClock,
)
from rift_invariant_engine import Invariant, InvariantEvaluationContext, InvariantEvaluator

StateT = TypeVar("StateT")

logger = logging.getLogger("rift.runner")


class ExperimentConfigurationError(ValueError):
    """The experiment, scenario binding, and invariants do not describe the same scenario."""


class ScenarioEnvironment(Protocol[StateT]):
    """One isolated, resettable instance of a scenario's external system."""

    def reset(self) -> None: ...

    def snapshot(self) -> StateT: ...

    def snapshot_json(self, state: StateT) -> dict[str, JsonValue]: ...

    def tool_handlers(self) -> Mapping[str, ToolHandler]: ...

    def tool_specs(self) -> tuple[ToolSpec, ...]: ...


class ScenarioBinding(Protocol[StateT]):
    """Connects a declarative ``ScenarioSpec`` to executable state, tools and invariants."""

    @property
    def spec(self) -> ScenarioSpec: ...

    def create_environment(self) -> ScenarioEnvironment[StateT]: ...

    def invariants(self) -> Sequence[Invariant[StateT]]: ...


class ExperimentRunner(Generic[StateT]):
    """Run a baseline and a faulted variant from equivalent fresh environments and compare them.

    Sequencing only: tools come from the binding, faults from the executor, correctness from the
    invariant engine, and behavior from the adapter.
    """

    def __init__(self, *, clock: Clock | None = None, sleeper: Sleeper | None = None) -> None:
        self._clock = clock or SystemClock()
        self._sleeper = sleeper

    async def run(
        self,
        experiment: ExperimentSpec,
        binding: ScenarioBinding[StateT],
        adapter: AgentAdapter,
    ) -> ExperimentReport:
        self._validate(experiment, binding)
        logger.info(
            "experiment.start id=%s adapter=%s rules=%d",
            experiment.experiment_id,
            adapter.name,
            len(experiment.fault_rules),
        )
        baseline = await self.run_once(experiment, binding, adapter, RunMode.BASELINE)
        faulted = await self.run_once(experiment, binding, adapter, RunMode.FAULTED)

        if baseline.initial_state != faulted.initial_state:
            raise ExperimentConfigurationError(
                "baseline and faulted runs did not start from equivalent state"
            )

        comparison = compare(baseline, faulted, experiment.fault_rules)
        logger.info(
            "experiment.done id=%s verdict=%s", experiment.experiment_id, comparison.verdict
        )
        return ExperimentReport(
            experiment=experiment,
            adapter=AdapterIdentity(name=adapter.name, version=adapter.version),
            baseline=baseline,
            faulted=faulted,
            comparison=comparison,
        )

    async def run_once(
        self,
        experiment: ExperimentSpec,
        binding: ScenarioBinding[StateT],
        adapter: AgentAdapter,
        mode: RunMode,
    ) -> RunReport:
        context = ExecutionContext(
            experiment_id=experiment.experiment_id,
            run_id=f"{experiment.experiment_id}:{mode.value}",
            seed=experiment.seed,
            run_mode=mode,
        )
        # A fresh environment *and* a reset: isolation does not depend on reset being perfect.
        environment = binding.create_environment()
        environment.reset()
        before = environment.snapshot()
        initial_state = environment.snapshot_json(before)
        # Verify against the experiment's own declaration, which _validate has already tied to
        # the binding. The declaration must come from an independent source (see ADR-006).
        declared_state = experiment.scenario.initial_state
        if declared_state and declared_state != initial_state:
            drift = [difference.path for difference in diff_states(declared_state, initial_state)]
            raise ExperimentConfigurationError(
                f"{experiment.scenario.scenario_id} reset state differs from its declared "
                f"initial_state at: {', '.join(drift)}"
            )

        recorder = InMemoryInvocationRecorder()
        executor = FaultInjectingToolExecutor(
            experiment.fault_rules,
            clock=self._clock,
            sleeper=self._sleeper,
            recorder=recorder,
        )
        task = AgentTask(
            scenario_id=binding.spec.scenario_id,
            instruction=binding.spec.task,
        )
        gateway = ExecutorToolGateway(
            executor=executor,
            handlers=environment.tool_handlers(),
            specs=environment.tool_specs(),
            execution_context=context,
            max_tool_calls=task.max_tool_calls,
        )

        try:
            agent_output = await adapter.run(task, gateway)
        except Exception as error:  # An adapter crash is evidence; state is still evaluated.
            logger.warning("agent.crashed run=%s error=%r", context.run_id, error)
            agent_output = AgentRunOutput(
                status=AgentStatus.CRASHED,
                tool_calls=gateway.calls_made,
                metadata={"error": f"{type(error).__name__}: {error}"},
            )

        after = environment.snapshot()
        final_state = environment.snapshot_json(after)
        summary = InvariantEvaluator(binding.invariants()).evaluate(
            InvariantEvaluationContext(before_state=before, after_state=after)
        )
        invocations = recorder.records
        outcome = derive_outcome(summary.results)
        result = ExperimentRunResult(
            context=context,
            outcome=outcome,
            tool_invocations=invocations,
            state_snapshot=StateSnapshot(
                snapshot_id=f"{context.run_id}:final",
                run_id=context.run_id,
                captured_at=self._clock.now(),
                state=final_state,
            ),
            invariant_results=summary.results,
            agent_response=agent_output.final_message,
        )
        logger.info(
            "run.done run=%s outcome=%s agent=%s calls=%d",
            context.run_id,
            outcome,
            agent_output.status,
            len(invocations),
        )
        return RunReport(
            mode=mode,
            result=result,
            agent=agent_output,
            classification=classify(outcome, agent_output),
            initial_state=initial_state,
            fired_fault_rule_ids=fired_rule_ids(invocations),
            fingerprint=fingerprint(
                invocations=invocations,
                final_state=final_state,
                results=summary.results,
                agent=agent_output,
            ),
        )

    @staticmethod
    def _validate(experiment: ExperimentSpec, binding: ScenarioBinding[StateT]) -> None:
        declared = experiment.scenario
        bound = binding.spec
        if (declared.scenario_id, declared.version) != (bound.scenario_id, bound.version):
            raise ExperimentConfigurationError(
                f"experiment targets {declared.scenario_id} v{declared.version} but the binding "
                f"provides {bound.scenario_id} v{bound.version}"
            )
        invariant_names = tuple(invariant.name for invariant in binding.invariants())
        if declared.invariant_ids and declared.invariant_ids != invariant_names:
            raise ExperimentConfigurationError(
                f"declared invariants {declared.invariant_ids} do not match "
                f"evaluated invariants {invariant_names}"
            )
        handlers = binding.create_environment().tool_handlers()
        missing = [name for name in declared.tool_names if name not in handlers]
        if missing:
            raise ExperimentConfigurationError(f"scenario declares unbound tools: {missing}")
        if declared != bound:
            fields = [
                name
                for name in type(declared).model_fields
                if getattr(declared, name) != getattr(bound, name)
            ]
            raise ExperimentConfigurationError(
                f"experiment declares {declared.scenario_id} v{declared.version} with different "
                f"content from the bound scenario; differing fields: {', '.join(fields)}"
            )
