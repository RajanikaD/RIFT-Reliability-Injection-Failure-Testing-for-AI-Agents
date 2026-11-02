"""Enforce the architecture's dependency rules by parsing imports, not by convention."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

PACKAGES = {
    "rift_core": ROOT / "packages/rift_core/src/rift_core",
    "rift_fault_engine": ROOT / "packages/rift_fault_engine/src/rift_fault_engine",
    "rift_invariant_engine": ROOT / "packages/rift_invariant_engine/src/rift_invariant_engine",
    "rift_agent_adapters": ROOT / "packages/rift_agent_adapters/src/rift_agent_adapters",
    "rift_experiment_runner": ROOT / "packages/rift_experiment_runner/src/rift_experiment_runner",
}

FIRST_PARTY = {
    "rift_core",
    "rift_fault_engine",
    "rift_invariant_engine",
    "rift_agent_adapters",
    "rift_experiment_runner",
    "rift_api",
    "rift_cli",
    "commerce_demo",
}

# Allowed first-party imports for each package (besides itself).
ALLOWED = {
    "rift_core": set(),
    "rift_fault_engine": {"rift_core"},
    "rift_invariant_engine": {"rift_core"},
    "rift_agent_adapters": {"rift_core"},
    "rift_experiment_runner": {"rift_core", "rift_fault_engine", "rift_invariant_engine"},
}

# Infrastructure and provider libraries that must never reach the core packages.
FORBIDDEN_THIRD_PARTY = {"fastapi", "starlette", "uvicorn", "sqlalchemy", "openai", "langchain"}


def imported_roots(package_root: Path) -> set[str]:
    roots: set[str] = set()
    for source_path in package_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.partition(".")[0])
    return roots


@pytest.mark.parametrize("package", list(PACKAGES))
def test_package_imports_only_allowed_first_party_packages(package: str) -> None:
    roots = imported_roots(PACKAGES[package])
    first_party = (roots & FIRST_PARTY) - {package}
    assert first_party <= ALLOWED[package], first_party - ALLOWED[package]


@pytest.mark.parametrize("package", list(PACKAGES))
def test_package_has_no_infrastructure_or_provider_dependencies(package: str) -> None:
    assert imported_roots(PACKAGES[package]).isdisjoint(FORBIDDEN_THIRD_PARTY)


def test_generic_invariant_engine_does_not_import_scenario_or_infrastructure_packages() -> None:
    """Original boundary test from the invariant-engine work, kept verbatim in intent."""

    engine_root = (
        Path(__file__).parents[1]
        / "packages"
        / "rift_invariant_engine"
        / "src"
        / "rift_invariant_engine"
    )
    forbidden_roots = {
        "commerce_demo",
        "rift_api",
        "rift_fault_engine",
    }

    imported: set[str] = set()
    for source_path in engine_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.partition(".")[0])

    assert imported.isdisjoint(forbidden_roots)
