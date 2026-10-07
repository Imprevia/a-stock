"""Repository-native import/layer checks for the market-environment package."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


PACKAGE_ROOT = Path("src/market_environment")
PACKAGE_NAME = "src.market_environment"


def module_name(path: Path) -> str:
    parts = path.with_suffix("").parts
    return ".".join(parts[:-1] if path.name == "__init__.py" else parts)


def imported_modules(module: str, tree: ast.AST) -> set[str]:
    package = module if module.rsplit(".", 1)[-1] == "__init__" else module.rpartition(".")[0]
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imports.add(
                    importlib.util.resolve_name(
                        "." * node.level + (node.module or ""),
                        package,
                    )
                )
            elif node.module:
                imports.add(node.module)
    return imports


def _matches(imported: str, prefix: str) -> bool:
    return imported == prefix or imported.startswith(f"{prefix}.")


def violations_for_source(module: str, source: str) -> list[str]:
    tree = ast.parse(source)
    imported = imported_modules(module, tree)
    violations: list[str] = []

    if module.startswith(f"{PACKAGE_NAME}.domain"):
        forbidden = (
            "fastapi",
            "sqlalchemy",
            "requests",
            f"{PACKAGE_NAME}.application",
            f"{PACKAGE_NAME}.interfaces",
            f"{PACKAGE_NAME}.infrastructure",
            f"{PACKAGE_NAME}.service",
            f"{PACKAGE_NAME}.providers",
            f"{PACKAGE_NAME}.snapshot_store",
            f"{PACKAGE_NAME}.collection",
        )
        for value in sorted(imported):
            if any(_matches(value, prefix) for prefix in forbidden):
                violations.append(f"{module}: domain imports {value}")

    if module.startswith(f"{PACKAGE_NAME}.application"):
        forbidden = (
            "fastapi",
            "sqlalchemy",
            "requests",
            f"{PACKAGE_NAME}.interfaces",
            f"{PACKAGE_NAME}.infrastructure",
            f"{PACKAGE_NAME}.providers",
            f"{PACKAGE_NAME}.snapshot_store",
            f"{PACKAGE_NAME}.service",
        )
        for value in sorted(imported):
            if any(_matches(value, prefix) for prefix in forbidden):
                violations.append(f"{module}: application imports {value}")

    if module.startswith(f"{PACKAGE_NAME}.infrastructure"):
        for value in sorted(imported):
            if _matches(value, f"{PACKAGE_NAME}.interfaces"):
                violations.append(f"{module}: infrastructure imports {value}")

    if module.startswith(f"{PACKAGE_NAME}.application.queries"):
        for value in sorted(imported):
            if any(
                _matches(value, prefix)
                for prefix in (
                    f"{PACKAGE_NAME}.providers",
                    f"{PACKAGE_NAME}.infrastructure",
                    f"{PACKAGE_NAME}.application.collection",
                )
            ):
                violations.append(f"{module}: query imports provider/collector module {value}")

    if module.startswith(f"{PACKAGE_NAME}.interfaces.http.routers"):
        for value in sorted(imported):
            if any(
                _matches(value, prefix)
                for prefix in (
                    f"{PACKAGE_NAME}.providers",
                    f"{PACKAGE_NAME}.snapshot_store",
                    f"{PACKAGE_NAME}.infrastructure",
                    f"{PACKAGE_NAME}.service",
                )
            ):
                violations.append(f"{module}: router imports concrete runtime adapter {value}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {
                    "SnapshotStore",
                    "MarketDataProvider",
                    "CollectionCoordinator",
                    "ThreadPoolExecutor",
                }:
                    violations.append(f"{module}: router constructs {node.func.id}")

    if module == f"{PACKAGE_NAME}.api":
        allowed_imports = {f"{PACKAGE_NAME}.bootstrap.app", "__future__"}
        for value in imported:
            if value not in allowed_imports:
                violations.append(f"{module}: non-thin entry-point import {value}")
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)]
        if not any(
            isinstance(target, ast.Name) and target.id == "app"
            for node in assignments
            for target in node.targets
        ):
            violations.append(f"{module}: missing app assignment")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "create_schema" and (
                module.startswith(f"{PACKAGE_NAME}.bootstrap")
                or module.startswith(f"{PACKAGE_NAME}.application")
                or module.startswith(f"{PACKAGE_NAME}.interfaces")
            ):
                violations.append(f"{module}: runtime schema creation is forbidden")
    return violations


def check_package(root: Path = PACKAGE_ROOT) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        module = module_name(path)
        violations.extend(violations_for_source(module, path.read_text(encoding="utf-8")))
    return violations


def main() -> int:
    violations = check_package()
    if violations:
        print("\n".join(violations))
        return 1
    print("market-environment architecture: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
