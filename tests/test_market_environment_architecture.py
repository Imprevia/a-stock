from __future__ import annotations

from pathlib import Path

from scripts.check_market_environment_architecture import check_package, violations_for_source


def test_refactored_market_environment_package_satisfies_layer_rules() -> None:
    assert check_package(Path("src/market_environment")) == []


def test_architecture_check_rejects_representative_forbidden_imports() -> None:
    violations = violations_for_source(
        "src.market_environment.application.queries.fixture",
        "from src.market_environment.providers import MarketDataProvider\n",
    )
    assert any("application imports" in item for item in violations)

    violations = violations_for_source(
        "src.market_environment.domain.models.fixture",
        "from fastapi import FastAPI\n",
    )
    assert any("domain imports" in item for item in violations)


def test_architecture_check_rejects_non_thin_api_entrypoint() -> None:
    violations = violations_for_source(
        "src.market_environment.api",
        "from src.market_environment.service import MarketEnvironmentService\n",
    )
    assert any("non-thin entry-point import" in item for item in violations)
