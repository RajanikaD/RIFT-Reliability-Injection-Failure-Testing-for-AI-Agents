import ast
from pathlib import Path


def test_generic_invariant_engine_does_not_import_scenario_or_infrastructure_packages() -> None:
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

    imported_roots: set[str] = set()
    for source_path in engine_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.partition(".")[0])

    assert imported_roots.isdisjoint(forbidden_roots)
