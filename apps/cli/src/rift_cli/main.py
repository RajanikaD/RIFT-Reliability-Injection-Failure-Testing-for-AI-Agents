"""``rift`` command-line interface for running local reliability experiments."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from commerce_demo.agents import AGENT_PROFILES
from commerce_demo.fault_cases import FAULT_CASES
from commerce_demo.models import CommerceSnapshot
from commerce_demo.scenario import CommerceScenarioBinding, commerce_experiment
from rift_core import ExperimentSpec
from rift_experiment_runner import (
    ExperimentConfigurationError,
    ExperimentReport,
    ExperimentRunner,
    render_text,
)

EXIT_OK = 0
EXIT_NOT_RESILIENT = 1
EXIT_USAGE = 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )
    try:
        return int(args.handler(args))
    except (ExperimentConfigurationError, ValidationError, ValueError) as error:
        print(f"rift: configuration error: {error}", file=sys.stderr)
        return EXIT_USAGE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rift",
        description="Reliability Injection & Failure Testing for tool-using AI agents.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    commands = parser.add_subparsers(required=True, metavar="command")

    list_parser = commands.add_parser("list", help="list agent profiles and fault cases")
    list_parser.set_defaults(handler=_list)

    run_parser = commands.add_parser("run", help="run one baseline-vs-faulted experiment")
    run_parser.add_argument("--agent", choices=sorted(AGENT_PROFILES), default="reconciling")
    source = run_parser.add_mutually_exclusive_group()
    source.add_argument("--fault", choices=list(FAULT_CASES), default="refund-timeout-after-commit")
    source.add_argument(
        "--spec", type=Path, help="JSON ExperimentSpec file (scenario must be commerce)"
    )
    run_parser.add_argument("--seed", type=int, default=0)
    run_parser.add_argument("--json", type=Path, help="also write the full report as JSON")
    run_parser.add_argument("--no-trace", action="store_true", help="omit invocation traces")
    run_parser.add_argument(
        "--strict", action="store_true", help="exit 1 unless the verdict is resilient"
    )
    run_parser.set_defaults(handler=_run)

    demo_parser = commands.add_parser("demo", help="run every agent against every fault case")
    demo_parser.add_argument("--json", type=Path, help="write all reports to this JSON file")
    demo_parser.set_defaults(handler=_demo)
    return parser


def _list(_args: argparse.Namespace) -> int:
    print("Agent profiles:")
    for name, factory in AGENT_PROFILES.items():
        doc = (factory.__doc__ or "").strip().splitlines()[0]
        print(f"  {name:<13} {doc}")
    print("\nFault cases:")
    for case in FAULT_CASES.values():
        print(f"  {case.name:<35} {case.summary}")
    return EXIT_OK


def _run(args: argparse.Namespace) -> int:
    if args.spec is not None:
        experiment = ExperimentSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
    else:
        case = FAULT_CASES[args.fault]
        experiment = commerce_experiment(
            f"{args.agent}--{case.name}", case.rules, seed=args.seed, description=case.summary
        )
    report = _execute(experiment, args.agent)
    print(render_text(report, show_trace=not args.no_trace))
    if args.json is not None:
        args.json.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nJSON report written to {args.json}")
    if args.strict and report.comparison.verdict.value != "resilient":
        return EXIT_NOT_RESILIENT
    return EXIT_OK


def _demo(args: argparse.Namespace) -> int:
    agents = list(AGENT_PROFILES)
    cases = [name for name in FAULT_CASES if name != "none"]
    reports: list[ExperimentReport] = []
    width = max(len(name) for name in cases) + 2
    print("RIFT demo: commerce.cancel_order - faulted-run classification per agent")
    print(
        "(correct = state right and agent says so; silent_failure = state wrong, agent says ok)\n"
    )
    print((" " * width + "".join(f"{agent:<20}" for agent in agents)).rstrip())
    for case_name in cases:
        case = FAULT_CASES[case_name]
        cells = []
        for agent in agents:
            report = _execute(commerce_experiment(f"{agent}--{case_name}", case.rules), agent)
            reports.append(report)
            cells.append(f"{report.faulted.classification.value:<20}")
        print((f"{case_name:<{width}}" + "".join(cells)).rstrip())
    if args.json is not None:
        payload = [json.loads(report.model_dump_json()) for report in reports]
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\n{len(reports)} reports written to {args.json}")
    print("\nInspect one: rift run --agent retrying --fault refund-timeout-after-commit")
    return EXIT_OK


def _execute(experiment: ExperimentSpec, agent: str) -> ExperimentReport:
    runner: ExperimentRunner[CommerceSnapshot] = ExperimentRunner()
    return asyncio.run(runner.run(experiment, CommerceScenarioBinding(), AGENT_PROFILES[agent]()))


if __name__ == "__main__":
    raise SystemExit(main())
