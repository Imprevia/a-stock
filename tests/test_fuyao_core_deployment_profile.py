from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "a-stock"
OFF_VALUES = ROOT / "deploy" / "truenas" / "values-fuyao-core-off.yaml"
ENABLED_VALUES = ROOT / "deploy" / "truenas" / "values-fuyao-core-enabled.yaml"
VALIDATOR = ROOT / "scripts" / "validate-scheduling-packet.py"
HELM = os.getenv("HELM_BINARY") or shutil.which("helm")
IMAGE = "localhost/a-stock-market-environment:20261017-005702-d12dae3"


def _load_values(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


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


def _environment(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    deployment = _resource(documents, "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    return {item["name"]: item for item in container["env"]}


def _write_documents(path: Path, documents: list[dict[str, Any]]) -> None:
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8")


def _run_validator(command: str, *arguments: str, payload: str = ""):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), command, *arguments],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


def test_fuyao_core_profiles_differ_only_by_formal_enabled_flag() -> None:
    off = _load_values(OFF_VALUES)
    enabled = _load_values(ENABLED_VALUES)
    assert off["marketEnvironment"]["fuyao"]["datasets"]["core"] == {
        "enabled": False,
        "approvedRevision": "fuyao-market-v2",
        "shadowEnabled": False,
    }
    assert enabled["marketEnvironment"]["fuyao"]["datasets"]["core"] == {
        "enabled": True,
        "approvedRevision": "fuyao-market-v2",
        "shadowEnabled": False,
    }
    expected = copy.deepcopy(enabled)
    expected["marketEnvironment"]["fuyao"]["datasets"]["core"]["enabled"] = False
    assert off == expected


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("values_path", "enabled"),
    ((OFF_VALUES, "0"), (ENABLED_VALUES, "1")),
)
def test_fuyao_core_profiles_are_complete_hook_free_packets(
    values_path: Path, enabled: str
) -> None:
    documents = _render(values_path)
    environment = _environment(documents)
    rendered = yaml.safe_dump_all(documents, sort_keys=True)

    assert not any(item.get("kind") in {"CronJob", "Job", "Secret"} for item in documents)
    assert environment["MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED"]["value"] == enabled
    assert environment["MARKET_ENVIRONMENT_FUYAO_CORE_APPROVED_REVISION"]["value"] == "fuyao-market-v2"
    assert environment["MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED"]["value"] == "0"
    assert environment["MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED"]["value"] == "1"
    assert environment["MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED"]["value"] == "1"
    assert environment["MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED"]["value"] == "1"
    assert environment["MARKET_ENVIRONMENT_FUYAO_API_KEY"]["valueFrom"] == {
        "secretKeyRef": {
            "name": "a-stock-market-provider",
            "key": "MARKET_ENVIRONMENT_FUYAO_API_KEY",
            "optional": True,
        }
    }
    assert "actual-api-key" not in rendered

    completed = _run_validator(
        "validate-core-packet",
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--require-enabled",
        enabled,
        payload=rendered,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_core_config_validator_accepts_only_formal_enabled_delta(tmp_path: Path) -> None:
    off_path = tmp_path / "off.yaml"
    enabled_path = tmp_path / "enabled.yaml"
    _write_documents(off_path, _render(OFF_VALUES))
    _write_documents(enabled_path, _render(ENABLED_VALUES))

    completed = _run_validator(
        "compare-core-config-only",
        "--current",
        str(off_path),
        "--desired",
        str(enabled_path),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        IMAGE,
        "--from-enabled",
        "0",
        "--to-enabled",
        "1",
    )
    assert completed.returncode == 0, completed.stderr


def _wrong_revision(documents: list[dict[str, Any]]) -> None:
    _environment(documents)["MARKET_ENVIRONMENT_FUYAO_CORE_APPROVED_REVISION"]["value"] = "fuyao-market-v1"


def _shadow_enabled(documents: list[dict[str, Any]]) -> None:
    _environment(documents)["MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED"]["value"] = "1"


def _image_drift(documents: list[dict[str, Any]]) -> None:
    _resource(documents, "Deployment")["spec"]["template"]["spec"]["containers"][0]["image"] = "other:image"


def _secret_drift(documents: list[dict[str, Any]]) -> None:
    _environment(documents)["MARKET_ENVIRONMENT_FUYAO_API_KEY"]["valueFrom"]["secretKeyRef"]["name"] = "other-secret"


def _database_drift(documents: list[dict[str, Any]]) -> None:
    _environment(documents)["MARKET_ENVIRONMENT_DATABASE_URL"]["valueFrom"]["secretKeyRef"]["name"] = "other-db"


def _service_drift(documents: list[dict[str, Any]]) -> None:
    _resource(documents, "Service")["spec"]["ports"][0]["port"] = 81


def _pvc_drift(documents: list[dict[str, Any]]) -> None:
    pvc = _resource(documents, "PersistentVolumeClaim")
    pvc["spec"]["resources"]["requests"]["storage"] = "9Gi"


def _scheduling_drift(documents: list[dict[str, Any]]) -> None:
    _environment(documents)["MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED"]["value"] = "0"


def _other_dataset_drift(documents: list[dict[str, Any]]) -> None:
    _environment(documents)["MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED"]["value"] = "0"


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "mutation",
    (
        _wrong_revision,
        _shadow_enabled,
        _image_drift,
        _secret_drift,
        _database_drift,
        _service_drift,
        _pvc_drift,
        _scheduling_drift,
        _other_dataset_drift,
    ),
)
def test_core_config_validator_rejects_unrelated_drift(
    tmp_path: Path,
    mutation: Callable[[list[dict[str, Any]]], None],
) -> None:
    off = _render(OFF_VALUES)
    enabled = _render(ENABLED_VALUES)
    mutation(enabled)
    off_path = tmp_path / "off.yaml"
    enabled_path = tmp_path / "enabled.yaml"
    _write_documents(off_path, off)
    _write_documents(enabled_path, enabled)

    completed = _run_validator(
        "compare-core-config-only",
        "--current",
        str(off_path),
        "--desired",
        str(enabled_path),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        IMAGE,
        "--from-enabled",
        "0",
        "--to-enabled",
        "1",
    )
    assert completed.returncode != 0


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize("kind", ("CronJob", "Job"))
def test_core_packet_rejects_application_scheduling_resources(kind: str) -> None:
    documents = _render(OFF_VALUES)
    documents.append(
        {
            "apiVersion": "batch/v1",
            "kind": kind,
            "metadata": {"name": "unreviewed", "namespace": "a-stock"},
            "spec": {},
        }
    )
    completed = _run_validator(
        "validate-core-packet",
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--require-enabled",
        "0",
        payload=yaml.safe_dump_all(documents),
    )
    assert completed.returncode != 0
