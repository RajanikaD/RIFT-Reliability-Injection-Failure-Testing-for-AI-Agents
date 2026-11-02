import json

from commerce_demo.scenario import commerce_experiment
from rift_cli.main import main
from rift_core import FaultRule, FaultType
from rift_experiment_runner import ExperimentReport


def test_list(capsys) -> None:
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    assert "reconciling" in output
    assert "refund-timeout-after-commit" in output


def test_run_writes_a_valid_json_report(tmp_path, capsys) -> None:
    path = tmp_path / "report.json"
    code = main(
        [
            "run",
            "--agent",
            "retrying",
            "--fault",
            "refund-timeout-after-commit",
            "--json",
            str(path),
        ]
    )

    assert code == 0
    assert "VERDICT: DEGRADED" in capsys.readouterr().out
    report = ExperimentReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert report.faulted.classification.value == "silent_failure"


def test_strict_mode_fails_when_not_resilient() -> None:
    args = ["run", "--agent", "retrying", "--fault", "refund-timeout-after-commit", "--strict"]
    assert main(args) == 1
    assert (
        main(
            ["run", "--agent", "reconciling", "--fault", "refund-timeout-after-commit", "--strict"]
        )
        == 0
    )


def test_run_from_spec_file(tmp_path, capsys) -> None:
    rule = FaultRule(
        fault_rule_id="slow-refund",
        tool_name="refund_payment",
        invocation_number=1,
        fault_type=FaultType.TIMEOUT_BEFORE_CALL,
    )
    spec = tmp_path / "spec.json"
    spec.write_text(commerce_experiment("from-file", [rule]).model_dump_json(), encoding="utf-8")

    assert main(["run", "--spec", str(spec), "--agent", "idempotent", "--no-trace"]) == 0
    assert "VERDICT: RESILIENT" in capsys.readouterr().out


def test_invalid_spec_is_a_usage_error(tmp_path, capsys) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"experiment_id": "x"}), encoding="utf-8")
    assert main(["run", "--spec", str(spec)]) == 2
    assert "configuration error" in capsys.readouterr().err


def test_demo_runs_the_whole_matrix(tmp_path, capsys) -> None:
    path = tmp_path / "all.json"
    assert main(["demo", "--json", str(path)]) == 0
    assert "silent_failure" in capsys.readouterr().out
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 36
