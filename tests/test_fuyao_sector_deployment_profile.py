from __future__ import annotations

import copy
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "a-stock"
ENABLED_VALUES = ROOT / "deploy" / "truenas" / "values-fuyao-sectors-enabled.yaml"
OFF_VALUES = ROOT / "deploy" / "truenas" / "values-fuyao-sectors-off.yaml"
HELM = os.getenv("HELM_BINARY") or shutil.which("helm")
FUYAO_REVISION = "fuyao-market-v2"


def _load_values(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _render(path: Path) -> list[dict[str, Any]]:
    completed = subprocess.run(
        [
            str(HELM),
            "template",
            "a-stock",
            str(CHART),
            "--namespace",
            "a-stock",
            "--values",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        document
        for document in yaml.safe_load_all(completed.stdout)
        if isinstance(document, dict)
    ]


def _resource(documents: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(document for document in documents if document.get("kind") == kind)


def _environment(container: dict[str, Any]) -> dict[str, Any]:
    return {
        item["name"]: item.get("value", item.get("valueFrom"))
        for item in container["env"]
    }


def _deployment_environment(documents: list[dict[str, Any]]) -> dict[str, Any]:
    deployment = _resource(documents, "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    return _environment(container)


def test_fuyao_sector_rollback_values_change_only_the_enabled_flag() -> None:
    enabled = _load_values(ENABLED_VALUES)
    rolled_back = _load_values(OFF_VALUES)
    sectors = enabled["marketEnvironment"]["fuyao"]["datasets"]["sectors"]
    rollback_sectors = rolled_back["marketEnvironment"]["fuyao"]["datasets"]["sectors"]

    assert sectors == {
        "enabled": True,
        "approvedRevision": FUYAO_REVISION,
        "shadowEnabled": False,
    }
    assert rollback_sectors == {
        "enabled": False,
        "approvedRevision": FUYAO_REVISION,
        "shadowEnabled": False,
    }

    expected_rollback = copy.deepcopy(enabled)
    expected_rollback["marketEnvironment"]["fuyao"]["datasets"]["sectors"]["enabled"] = False
    assert rolled_back == expected_rollback


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("values_path", "expected_enabled"),
    ((ENABLED_VALUES, "1"), (OFF_VALUES, "0")),
)
def test_fuyao_sector_profiles_render_only_the_reviewed_runtime_configuration(
    values_path: Path, expected_enabled: str
) -> None:
    documents = _render(values_path)
    environment = _deployment_environment(documents)
    rendered = yaml.safe_dump_all(documents, sort_keys=True)

    assert all(document.get("kind") != "Secret" for document in documents)
    assert all(document.get("kind") != "CronJob" for document in documents)
    assert "a-stock-data-collection" not in rendered
    assert "market-data-collection" not in rendered

    assert environment["MARKET_ENVIRONMENT_FUYAO_API_KEY"] == {
        "secretKeyRef": {
            "name": "a-stock-market-provider",
            "key": "MARKET_ENVIRONMENT_FUYAO_API_KEY",
            "optional": True,
        }
    }
    assert environment["MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED"] == expected_enabled
    assert environment["MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION"] == FUYAO_REVISION
    assert environment["MARKET_ENVIRONMENT_FUYAO_SECTORS_SHADOW_ENABLED"] == "0"
    assert environment["MARKET_ENVIRONMENT_EASTMONEY_SECTOR_ENRICHMENT_ENABLED"] == "0"
    assert environment["MARKET_ENVIRONMENT_SCRAPLING_ENABLED"] == "0"
    assert environment["MARKET_ENVIRONMENT_SCRAPLING_ALLOWLIST"] == "[]"

    for dataset in ("CORE", "BREADTH", "ACTIVE_DIRECTION"):
        assert environment[f"MARKET_ENVIRONMENT_FUYAO_{dataset}_ENABLED"] == "0"
        assert environment[f"MARKET_ENVIRONMENT_FUYAO_{dataset}_APPROVED_REVISION"] == ""
        assert environment[f"MARKET_ENVIRONMENT_FUYAO_{dataset}_SHADOW_ENABLED"] == "0"

    assert "actual-api-key" not in rendered
    assert "Authorization" not in rendered


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_fuyao_sector_rollback_render_changes_only_the_sector_switch() -> None:
    enabled = _render(ENABLED_VALUES)
    rolled_back = _render(OFF_VALUES)

    enabled_environment = _deployment_environment(enabled)
    rollback_environment = _deployment_environment(rolled_back)
    expected_environment = copy.deepcopy(enabled_environment)
    expected_environment["MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED"] = "0"

    assert rollback_environment == expected_environment

    enabled_deployment = _resource(enabled, "Deployment")
    rollback_deployment = _resource(rolled_back, "Deployment")
    enabled_container = enabled_deployment["spec"]["template"]["spec"]["containers"][0]
    rollback_container = rollback_deployment["spec"]["template"]["spec"]["containers"][0]
    enabled_container["env"] = []
    rollback_container["env"] = []
    assert rolled_back == enabled
