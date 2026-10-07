"""Repository-native import/layer checks for the market-environment package."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


PACKAGE_ROOT = Path("src/market_environment")
PACKAGE_NAME = "src.market_environment"

# The root package is a compatibility boundary during the staged migration.
# The target value is the owning top-level package for implementation code;
# root files themselves remain stable entries or forwarding shims only.
ROOT_MODULE_TARGETS = {
    "__init__.py": "package",
    "api.py": "bootstrap",
    "calculations.py": "domain",
    "cli.py": "interfaces",
    "collection.py": "infrastructure",
    "database.py": "infrastructure",
    "date_relabel.py": "infrastructure",
    "fuyao.py": "infrastructure",
    "fuyao_config.py": "infrastructure",
    "fuyao_market.py": "infrastructure",
    "fuyao_request_gate.py": "infrastructure",
    "industry_mapping.py": "infrastructure",
    "limit_ecosystem.py": "application",
    "limit_facts.py": "domain",
    "limit_promotion.py": "application",
    "postgres_compat.py": "infrastructure",
    "postgres_migration.py": "infrastructure",
    "postgres_schema.py": "infrastructure",
    "provider_capability.py": "infrastructure",
    "provider_shadow.py": "infrastructure",
    "providers.py": "infrastructure",
    "refresh.py": "infrastructure",
    "schemas.py": "interfaces",
    "sector_enrichment.py": "infrastructure",
    "service.py": "infrastructure",
    "snapshot_migration.py": "infrastructure",
    "snapshot_store.py": "infrastructure",
    "tdx_config.py": "infrastructure",
    "tdx_daily.py": "infrastructure",
    "timezone_preferences.py": "application",
    "trading_sessions.py": "domain",
}
ROOT_MODULE_ALLOWLIST = frozenset(ROOT_MODULE_TARGETS)
VALID_ROOT_TARGET_PACKAGES = frozenset(
    {"package", "bootstrap", "interfaces", "application", "domain", "infrastructure"}
)
ROOT_COMPATIBILITY_SHIMS = frozenset(
    {
        "calculations.py",
        "collection.py",
        "date_relabel.py",
        "fuyao.py",
        "fuyao_config.py",
        "fuyao_market.py",
        "fuyao_request_gate.py",
        "industry_mapping.py",
        "limit_facts.py",
        "postgres_compat.py",
        "postgres_migration.py",
        "provider_capability.py",
        "provider_shadow.py",
        "providers.py",
        "refresh.py",
        "schemas.py",
        "sector_enrichment.py",
        "service.py",
        "snapshot_migration.py",
        "snapshot_store.py",
        "tdx_config.py",
        "tdx_daily.py",
    }
)
RELOCATED_ROOT_IMPLEMENTATION_MODULES = frozenset(
    f"{PACKAGE_NAME}.{name.removesuffix('.py')}"
    for name in ROOT_COMPATIBILITY_SHIMS
    if name
    not in {
        "providers.py",
        "service.py",
        "snapshot_migration.py",
        "snapshot_store.py",
    }
)
# These seams avoid reversing the existing layer direction while the response
# DTO validation and effective-market-date policy are still being extracted.
ROOT_SHIM_INTERNAL_IMPORT_EXCEPTIONS = frozenset(
    {
        (
            f"{PACKAGE_NAME}.infrastructure.legacy.service",
            f"{PACKAGE_NAME}.schemas",
        ),
        (
            f"{PACKAGE_NAME}.infrastructure.materialization_support",
            f"{PACKAGE_NAME}.schemas",
        ),
        (
            f"{PACKAGE_NAME}.infrastructure.materialized_aggregate_factory",
            f"{PACKAGE_NAME}.schemas",
        ),
        (
            f"{PACKAGE_NAME}.infrastructure.providers.limits",
            f"{PACKAGE_NAME}.schemas",
        ),
        (
            f"{PACKAGE_NAME}.interfaces.http.dependencies",
            f"{PACKAGE_NAME}.refresh",
        ),
        (
            f"{PACKAGE_NAME}.interfaces.http.routers.collection",
            f"{PACKAGE_NAME}.collection",
        ),
    }
)


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

    is_internal_submodule = (
        module.startswith(f"{PACKAGE_NAME}.")
        and module.count(".") > PACKAGE_NAME.count(".") + 1
    )
    if is_internal_submodule:
        for value in sorted(imported & RELOCATED_ROOT_IMPLEMENTATION_MODULES):
            if (module, value) not in ROOT_SHIM_INTERNAL_IMPORT_EXCEPTIONS:
                violations.append(
                    f"{module}: internal module imports relocated root shim {value}"
                )

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


def violations_for_root_layout(
    root: Path = PACKAGE_ROOT,
    targets: dict[str, str] | None = None,
) -> list[str]:
    """Reject root-level modules that are not part of the migration inventory."""

    inventory = ROOT_MODULE_TARGETS if targets is None else targets
    listed = set(inventory)
    actual = {path.name for path in root.glob("*.py")}
    violations: list[str] = []
    for name in sorted(actual - listed):
        violations.append(
            f"{PACKAGE_NAME}: unlisted root module {name}; move it to a layer package "
            "or explicitly register a reviewed compatibility entry"
        )
    for name in sorted(listed - actual):
        violations.append(
            f"{PACKAGE_NAME}: root inventory lists missing module {name}; "
            "update the migration inventory after a reviewed relocation"
        )
    for name, target in sorted(inventory.items()):
        if target not in VALID_ROOT_TARGET_PACKAGES:
            violations.append(
                f"{PACKAGE_NAME}: root inventory declares invalid target package "
                f"{target!r} for {name}"
            )
    return violations


def violations_for_compatibility_shim(module: str, source: str) -> list[str]:
    """Ensure a compatibility shim contains imports/exports only."""

    if module.rsplit(".", 1)[-1] not in {
        name.removesuffix(".py") for name in ROOT_COMPATIBILITY_SHIMS
    }:
        return []
    tree = ast.parse(source)
    violations: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # module docstring
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Assign):
            targets = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if targets <= {"__all__"}:
                continue
        violations.append(
            f"{module}: compatibility shim contains non-forwarding "
            f"{type(node).__name__}"
        )
    return violations


def check_package(root: Path = PACKAGE_ROOT) -> list[str]:
    violations: list[str] = violations_for_root_layout(root)
    for path in sorted(root.rglob("*.py")):
        module = module_name(path)
        source = path.read_text(encoding="utf-8")
        violations.extend(violations_for_source(module, source))
        if path.parent == root:
            violations.extend(violations_for_compatibility_shim(module, source))
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
