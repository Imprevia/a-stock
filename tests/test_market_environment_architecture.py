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
