from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.check_market_environment_architecture import (
    check_package,
    violations_for_compatibility_shim,
    violations_for_root_layout,
    violations_for_source,
)


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

    violations = violations_for_source(
        "src.market_environment.infrastructure.providers.fixture",
        "from src.market_environment.fuyao_market import FuyaoMarketAdapter\n",
    )
    assert any("imports relocated root shim" in item for item in violations)


def test_architecture_check_rejects_vendor_imports_at_orchestration_boundaries() -> None:
    application_violations = violations_for_source(
        "src.market_environment.application.commands.fixture",
        "from mootdx.quotes import Quotes\n",
    )
    coordinator_violations = violations_for_source(
        "src.market_environment.infrastructure.collection.coordinator_fixture",
        "from src.market_environment.infrastructure.providers.fuyao.market "
        "import FuyaoMarketAdapter\n",
    )

    assert any("vendor import mootdx.quotes" in item for item in application_violations)
    assert any(
        "vendor import src.market_environment.infrastructure.providers.fuyao.market"
        in item
        for item in coordinator_violations
    )
    assert all("source adapter" in item for item in coordinator_violations)


def test_architecture_check_rejects_native_engine_response_types_above_transport() -> None:
    violations = violations_for_source(
        "src.market_environment.infrastructure.providers.fixture",
        "import requests as http_requests\n"
        "def validate(response: http_requests.Response) -> bool:\n"
        "    return response.status_code == 200\n",
    )

    assert any("requests.Response" in item for item in violations)
    assert any("use TransportResponse instead" in item for item in violations)


def test_architecture_check_rejects_unregistered_direct_network_calls_with_path() -> None:
    violations = violations_for_source(
        "src.market_environment.infrastructure.providers.fixture",
        "from urllib.request import urlopen as fetch\nfetch('https://example.invalid')\n",
    )

    assert any(
        item.startswith(
            "src/market_environment/infrastructure/providers/fixture.py:2: "
            "unregistered direct network call urllib.request.urlopen"
        )
        for item in violations
    )
    assert any("registered source/transport adapter" in item for item in violations)

    aliased_session = violations_for_source(
        "src.market_environment.infrastructure.providers.another_fixture",
        "from requests.sessions import Session as HttpSession\nHttpSession()\n",
    )
    assert any("requests.sessions.Session" in item for item in aliased_session)


def test_architecture_check_rejects_normal_runtime_legacy_provider_dependency() -> None:
    violations = violations_for_source(
        "src.market_environment.bootstrap.container",
        "from src.market_environment.infrastructure.legacy.providers "
        "import MarketDataProvider\n",
    )

    assert any("normal runtime imports legacy provider facade" in item for item in violations)


def test_architecture_check_rejects_nested_coordinator_compatibility_adapter() -> None:
    violations = violations_for_source(
        "src.market_environment.infrastructure.compatibility",
        "from src.market_environment.infrastructure.collection import "
        "CollectionCoordinator\n"
        "nested = CollectionCoordinator(provider, store)\n",
    )

    assert any("constructs a nested CollectionCoordinator" in item for item in violations)
    assert any("without lease, commit or rebuild" in item for item in violations)


def test_architecture_check_rejects_incomplete_dataset_and_source_registries() -> None:
    direct_constructor = violations_for_source(
        "src.market_environment.bootstrap.fixture",
        "from src.market_environment.application.collection import "
        "AcquisitionPlanRegistry\n"
        "plans = AcquisitionPlanRegistry(())\n",
    )
    missing_sources = violations_for_source(
        "src.market_environment.bootstrap.fixture",
        "from src.market_environment.application.collection import "
        "AcquisitionPlanRegistry\n"
        "plans = AcquisitionPlanRegistry.complete(())\n",
    )
    empty_sources = violations_for_source(
        "src.market_environment.bootstrap.fixture",
        "from src.market_environment.application.collection import "
        "AcquisitionPlanRegistry, SourceAdapterRegistry\n"
        "plans = AcquisitionPlanRegistry.complete(\n"
        "    (), source_adapters=SourceAdapterRegistry(())\n"
        ")\n",
    )

    assert any("AcquisitionPlanRegistry.complete" in item for item in direct_constructor)
    assert any("incomplete stable dataset registry" in item for item in missing_sources)
    assert any("requires source_adapters" in item for item in missing_sources)
    assert any("incomplete source adapter registry" in item for item in empty_sources)
    assert all("src/market_environment/bootstrap/fixture.py:" in item for item in missing_sources)


def test_architecture_check_rejects_non_thin_api_entrypoint() -> None:
    violations = violations_for_source(
        "src.market_environment.api",
        "from src.market_environment.service import MarketEnvironmentService\n",
    )
    assert any("non-thin entry-point import" in item for item in violations)


def test_root_layout_inventory_rejects_unlisted_modules(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "new_feature.py").write_text("VALUE = 1\n", encoding="utf-8")

    violations = violations_for_root_layout(tmp_path)

    assert any("unlisted root module new_feature.py" in item for item in violations)


def test_root_layout_inventory_rejects_missing_and_invalid_target_declarations(
    tmp_path: Path,
) -> None:
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")

    violations = violations_for_root_layout(
        tmp_path,
        {
            "__init__.py": "package",
            "missing.py": "misc",
        },
    )

    assert any("inventory lists missing module missing.py" in item for item in violations)
    assert any("invalid target package 'misc' for missing.py" in item for item in violations)


def test_compatibility_shim_rejects_business_logic() -> None:
    violations = violations_for_compatibility_shim(
        "src.market_environment.providers",
        "from .infrastructure.legacy.providers import *\n"
        "def new_business_rule():\n    return True\n",
    )

    assert any("non-forwarding FunctionDef" in item for item in violations)


def test_stable_root_entrypoints_and_shims_import_without_runtime_io() -> None:
    script = """
import importlib
import os
from pathlib import Path
from scripts.check_market_environment_architecture import ROOT_COMPATIBILITY_SHIMS

root = Path(os.environ['MARKET_ENVIRONMENT_IMPORT_TMP'])
os.chdir(root)
for name in (
    'src.market_environment.api',
    'src.market_environment.cli',
    *(
        f"src.market_environment.{filename.removesuffix('.py')}"
        for filename in ROOT_COMPATIBILITY_SHIMS
    ),
):
    importlib.import_module(name)

assert list(root.rglob('*.sqlite3')) == []
print('root imports are side-effect free')
"""
    with tempfile.TemporaryDirectory() as directory:
        environment = os.environ.copy()
        environment["MARKET_ENVIRONMENT_IMPORT_TMP"] = directory
        repository = str(Path.cwd())
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (repository, environment.get("PYTHONPATH", "")) if part
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "root imports are side-effect free"
