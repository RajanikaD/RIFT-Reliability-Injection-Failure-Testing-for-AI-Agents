"""D7 static policy checks for the API image. These run without a Docker engine.

The defect (Milestone 1 closeout, M1-D7): the image ran ``pip install .``, ignoring ``uv.lock``
(so each build could resolve different dependency versions), and ran as root. A real image build
is exercised in CI; these tests catch regressions locally.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
DOCKERFILE = ROOT / "apps/api/Dockerfile"


def policy_violations(dockerfile: str, packaged_roots: set[str]) -> list[str]:
    lines = [line.strip() for line in dockerfile.splitlines()]
    instructions = [line for line in lines if line and not line.startswith("#")]
    violations: list[str] = []

    if not any("uv.lock" in line for line in instructions if line.startswith("COPY")):
        violations.append("uv.lock is not copied into the image")
    installs = [line for line in instructions if line.startswith("RUN") and "install" in line]
    syncs = [line for line in instructions if line.startswith("RUN") and "uv sync" in line]
    if not syncs or not all("--locked" in line for line in syncs):
        violations.append("dependencies are not installed with `uv sync --locked`")
    if any("pip install" in line for line in installs):
        violations.append("pip install bypasses the lock file")

    users = [line.split(maxsplit=1)[1] for line in instructions if line.startswith("USER ")]
    if not users or users[-1] in {"root", "0"}:
        violations.append("the image does not switch to a non-root user")

    copied = {
        match.group(1)
        for line in instructions
        if (match := re.match(r"COPY\s+(\S+)\s+\S+$", line)) and "/src" in match.group(1)
    }
    missing = sorted(packaged_roots - copied)
    if missing:
        violations.append(f"packaged sources not copied: {missing}")
    return violations


def packaged_source_roots() -> set[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    packages = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    return {package.rsplit("/", 1)[0] for package in packages}


def test_api_image_follows_lock_and_non_root_policy() -> None:
    assert policy_violations(DOCKERFILE.read_text(encoding="utf-8"), packaged_source_roots()) == []


def test_policy_detects_the_milestone_1_dockerfile_defects() -> None:
    milestone_1 = """
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps/api/src ./apps/api/src
RUN pip install --no-cache-dir .
CMD ["uvicorn", "rift_api.main:app"]
"""
    violations = policy_violations(milestone_1, {"apps/api/src", "apps/cli/src"})
    assert "uv.lock is not copied into the image" in violations
    assert "the image does not switch to a non-root user" in violations
    assert "pip install bypasses the lock file" in violations
    assert any("apps/cli/src" in violation for violation in violations)
