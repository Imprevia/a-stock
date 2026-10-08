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

# All provider HTTP attempts now pass through the shared transport gateway.
# Keeping this empty inventory explicit prevents a new direct-network path.
REGISTERED_DIRECT_NETWORK_MODULES = frozenset()

# The coordinator still constructs the legacy collectors until the collector
# boundary is closed. Only its already-characterized imports are grandfathered;
# any new vendor dependency is rejected by the gate.
COORDINATOR_VENDOR_IMPORT_EXCEPTIONS = frozenset(
    {
        (
            f"{PACKAGE_NAME}.infrastructure.collection.coordinator",
            f"{PACKAGE_NAME}.infrastructure.providers",
        ),
        (
            f"{PACKAGE_NAME}.infrastructure.collection.coordinator",
            f"{PACKAGE_NAME}.infrastructure.providers.fuyao.config",
        ),
        (
            f"{PACKAGE_NAME}.infrastructure.collection.coordinator",
            f"{PACKAGE_NAME}.infrastructure.providers.fuyao.market",
        ),
    }
)

# Provider validators consume only the engine-neutral response contract.
NATIVE_RESPONSE_TYPE_EXCEPTIONS = frozenset()

NORMAL_RUNTIME_PROVIDER_MODULES = frozenset(
    {
        f"{PACKAGE_NAME}.bootstrap.container",
        f"{PACKAGE_NAME}.bootstrap.registries",
        f"{PACKAGE_NAME}.infrastructure.providers.runtime",
    }
)

VENDOR_IMPORT_PREFIXES = (
    "akshare",
    "aiohttp",
    "baostock",
    "httpx",
    "mootdx",
    "requests",
    "scrapling",
    "tushare",
    f"{PACKAGE_NAME}.fuyao",
    f"{PACKAGE_NAME}.fuyao_config",
    f"{PACKAGE_NAME}.fuyao_market",
    f"{PACKAGE_NAME}.fuyao_request_gate",
    f"{PACKAGE_NAME}.industry_mapping",
    f"{PACKAGE_NAME}.providers",
    f"{PACKAGE_NAME}.sector_enrichment",
    f"{PACKAGE_NAME}.tdx_config",
    f"{PACKAGE_NAME}.tdx_daily",
    f"{PACKAGE_NAME}.infrastructure.legacy.providers",
    f"{PACKAGE_NAME}.infrastructure.providers",
)

_NETWORK_CALLS = frozenset(
    {
        "aiohttp.ClientSession",
        "aiohttp.request",
        "http.client.HTTPConnection",
        "http.client.HTTPSConnection",
        "httpx.AsyncClient",
        "httpx.Client",
        "httpx.delete",
        "httpx.get",
        "httpx.head",
        "httpx.options",
        "httpx.patch",
        "httpx.post",
        "httpx.put",
        "httpx.request",
        "requests.Session",
        "requests.delete",
        "requests.get",
        "requests.head",
        "requests.options",
        "requests.patch",
        "requests.post",
        "requests.put",
        "requests.request",
        "requests.session",
        "socket.create_connection",
        "socket.socket",
        "urllib.request.build_opener",
        "urllib.request.install_opener",
        "urllib.request.urlretrieve",
        "urllib.request.urlopen",
    }
)

_COMPLETE_REGISTRY_TYPES = frozenset(
    {
        "AcquisitionPlanRegistry",
        "DatasetCollectorRegistry",
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


def _import_aliases(module: str, tree: ast.AST) -> dict[str, str]:
    package = (
        module
        if module.rsplit(".", 1)[-1] == "__init__"
        else module.rpartition(".")[0]
    )
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                aliases[local_name] = alias.name if alias.asname else local_name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imported_module = importlib.util.resolve_name(
                    "." * node.level + (node.module or ""),
                    package,
                )
            elif node.module:
                imported_module = node.module
            else:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = f"{imported_module}.{alias.name}"
    return aliases


def _qualified_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if not isinstance(node, ast.Attribute):
        return None
    parent = _qualified_name(node.value, aliases)
    return f"{parent}.{node.attr}" if parent else None


def _source_path(module: str, node: ast.AST | None = None) -> str:
    path = module.replace(".", "/")
    if path.endswith("/__init__"):
        path = path.removesuffix("/__init__") + "/__init__.py"
    else:
        path += ".py"
    line = getattr(node, "lineno", None)
    return f"{path}:{line}" if line is not None else path


def _is_coordinator_module(module: str) -> bool:
    parts = module.split(".")
    return any(part == "coordinator" or part.startswith("coordinator_") for part in parts)


def _is_native_response_type(name: str) -> bool:
    parts = name.split(".")
    if not parts or parts[0] not in {"aiohttp", "httpx", "requests", "scrapling"}:
        return False
    return parts[-1] in {"ClientResponse", "Response"}


def _is_direct_network_call(name: str | None) -> bool:
    if name is None:
        return False
    if name in _NETWORK_CALLS or name.startswith("scrapling."):
        return True
    parts = name.split(".")
    terminal = parts[-1]
    if parts[0] == "requests":
        return terminal in {
            "Session",
            "delete",
            "get",
            "head",
            "options",
            "patch",
            "post",
            "put",
            "request",
            "session",
        }
    if parts[0] == "httpx":
        return terminal in {
            "AsyncClient",
            "Client",
            "delete",
            "get",
            "head",
            "options",
            "patch",
            "post",
            "put",
            "request",
        }
    if name.startswith("urllib.request."):
        return terminal in {"build_opener", "install_opener", "urlopen", "urlretrieve"}
    return False


def _empty_collection(node: ast.AST) -> bool:
    return isinstance(node, (ast.List, ast.Set, ast.Tuple)) and not node.elts


def _registry_violations(
    module: str,
    tree: ast.AST,
    aliases: dict[str, str],
) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _qualified_name(node.func, aliases)
        if called is None:
            continue
        called_parts = called.split(".")
        registry_type = called_parts[-1]
        if registry_type in _COMPLETE_REGISTRY_TYPES:
            violations.append(
                f"{_source_path(module, node)}: incomplete {registry_type}; "
                f"construct it with {registry_type}.complete(...) before external I/O"
            )
            continue
        if called_parts[-2:] == ["AcquisitionPlanRegistry", "complete"]:
            if not node.args or _empty_collection(node.args[0]):
                violations.append(
                    f"{_source_path(module, node)}: incomplete stable dataset registry; "
                    "register acquisition plans for every DATASET_IDS entry"
                )
            source_keywords = [
                keyword
                for keyword in node.keywords
                if keyword.arg == "source_adapters"
            ]
            if not source_keywords:
                violations.append(
                    f"{_source_path(module, node)}: incomplete acquisition/source "
                    "registries; AcquisitionPlanRegistry.complete(...) requires "
                    "source_adapters=SourceAdapterRegistry(...) before external I/O"
                )
            elif any(
                isinstance(keyword.value, ast.Call)
                and (_qualified_name(keyword.value.func, aliases) or "").split(".")[-1]
                == "SourceAdapterRegistry"
                and (
                    not keyword.value.args
                    or _empty_collection(keyword.value.args[0])
                )
                for keyword in source_keywords
            ):
                violations.append(
                    f"{_source_path(module, node)}: incomplete source adapter registry; "
                    "register every source referenced by the dataset plans"
                )
        if called_parts[-2:] == ["DatasetCollectorRegistry", "complete"] and (
            not node.args or _empty_collection(node.args[0])
        ):
            violations.append(
                f"{_source_path(module, node)}: incomplete stable dataset registry; "
                "register collectors for every DATASET_IDS entry"
            )
        if registry_type == "SourceAdapterRegistry" and (
            not node.args or _empty_collection(node.args[0])
        ):
            violations.append(
                f"{_source_path(module, node)}: incomplete source adapter registry; "
                "register every source referenced by the dataset plans"
            )
    return violations


def _matches(imported: str, prefix: str) -> bool:
    return imported == prefix or imported.startswith(f"{prefix}.")


def violations_for_source(module: str, source: str) -> list[str]:
    tree = ast.parse(source)
    imported = imported_modules(module, tree)
    aliases = _import_aliases(module, tree)
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

    guarded_vendor_boundary = module.startswith(
        f"{PACKAGE_NAME}.application"
    ) or _is_coordinator_module(module)
    if guarded_vendor_boundary:
        for value in sorted(imported):
            if not any(_matches(value, prefix) for prefix in VENDOR_IMPORT_PREFIXES):
                continue
            if (module, value) in COORDINATOR_VENDOR_IMPORT_EXCEPTIONS:
                continue
            violations.append(
                f"{_source_path(module)}: vendor import {value} crosses the "
                "application/query/coordinator boundary; move provider mechanics "
                "behind a registered source adapter"
            )

    if module.startswith(f"{PACKAGE_NAME}.infrastructure"):
        for value in sorted(imported):
            if _matches(value, f"{PACKAGE_NAME}.interfaces"):
                violations.append(f"{module}: infrastructure imports {value}")

    if module in NORMAL_RUNTIME_PROVIDER_MODULES:
        for value in sorted(imported):
            if value == f"{PACKAGE_NAME}.providers" or _matches(
                value,
                f"{PACKAGE_NAME}.infrastructure.legacy.providers",
            ):
                violations.append(
                    f"{_source_path(module)}: normal runtime imports legacy "
                    f"provider facade {value}; depend on registered source adapters "
                    "or CollectorProviderRuntime"
                )

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

    native_response_uses: dict[str, ast.AST | None] = {
        imported_name: None
        for imported_name in aliases.values()
        if _is_native_response_type(imported_name)
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Attribute, ast.Name)):
            continue
        referenced_name = _qualified_name(node, aliases)
        if referenced_name is not None and _is_native_response_type(referenced_name):
            native_response_uses[referenced_name] = node

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            native_names = {
                name
                for name in (
                    "aiohttp.ClientResponse",
                    "httpx.Response",
                    "requests.Response",
                    "scrapling.Response",
                )
                if name in node.value
            }
            for native_name in native_names:
                native_response_uses[native_name] = node

    for native_name, node in sorted(native_response_uses.items()):
        if (module, native_name) in NATIVE_RESPONSE_TYPE_EXCEPTIONS:
            continue
        violations.append(
            f"{_source_path(module, node)}: native engine response type "
            f"{native_name} escapes the transport adapter; use "
            "TransportResponse instead"
        )

    if module not in REGISTERED_DIRECT_NETWORK_MODULES:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _qualified_name(node.func, aliases)
            if _is_direct_network_call(called):
                violations.append(
                    f"{_source_path(module, node)}: unregistered direct network call "
                    f"{called}; route it through a registered source/transport adapter"
                )

    if module == f"{PACKAGE_NAME}.infrastructure.compatibility":
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _qualified_name(node.func, aliases)
            if called is not None and called.split(".")[-1] == "CollectionCoordinator":
                violations.append(
                    f"{_source_path(module, node)}: compatibility shim constructs a "
                    "nested CollectionCoordinator; use a normalized source adapter "
                    "without lease, commit or rebuild side effects"
                )

    violations.extend(_registry_violations(module, tree, aliases))

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
