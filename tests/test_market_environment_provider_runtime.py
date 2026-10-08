from __future__ import annotations

import ast
from pathlib import Path

from src.market_environment.infrastructure.legacy.providers import MarketDataProvider
from src.market_environment.infrastructure.providers.runtime import (
    CollectorProviderRuntime,
    INDEX_SPECS,
)
from src.market_environment.providers import ProviderResult


def test_stable_provider_import_is_an_alias_to_the_normal_runtime() -> None:
    assert MarketDataProvider is CollectorProviderRuntime
    assert CollectorProviderRuntime.__bases__ == (object,)
    assert len(INDEX_SPECS) == 5
    assert ProviderResult.__module__.endswith("infrastructure.providers.runtime")


def test_legacy_provider_module_contains_exports_only() -> None:
    path = Path("src/market_environment/infrastructure/legacy/providers.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))

    assert not any(isinstance(node, (ast.ClassDef, ast.FunctionDef)) for node in tree.body)
    assert "requests" not in path.read_text(encoding="utf-8")


def test_normal_composition_has_no_legacy_provider_import() -> None:
    for path in (
        Path("src/market_environment/bootstrap/container.py"),
        Path("src/market_environment/bootstrap/registries.py"),
        Path("src/market_environment/infrastructure/providers/runtime.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "infrastructure.legacy.providers" not in source
        assert "legacy.providers" not in source
