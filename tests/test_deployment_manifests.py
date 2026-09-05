from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
K3S_DIR = ROOT / "deploy" / "k3s"
CHART_DIR = ROOT / "deploy" / "helm" / "a-stock"
TRUENAS_DIRECT_ACCESS_VALUES = ROOT / "deploy" / "truenas" / "values-secure-manual-collection.yaml"
HELM_BINARY = os.getenv("HELM_BINARY") or shutil.which("helm")
KUBECTL_BINARY = os.getenv("KUBECTL_BINARY") or shutil.which("kubectl")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _render_helm(*arguments: str) -> list[dict]:
    completed = subprocess.run(
        [
            str(HELM_BINARY),
            "template",
            "a-stock",
            str(CHART_DIR),
            "--namespace",
            "a-stock",
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [document for document in yaml.safe_load_all(completed.stdout) if document]


def _resource(documents: list[dict], kind: str) -> dict:
    return next(document for document in documents if document.get("kind") == kind)


def _environment(container: dict) -> dict[str, str]:
    return {item["name"]: item["value"] for item in container["env"]}


def test_kustomize_cronjob_uses_dashboard_image_pvc_and_security_boundary() -> None:
    kustomization = _load_yaml(K3S_DIR / "kustomization.yaml")
    deployment = _load_yaml(K3S_DIR / "deployment.yaml")
    service = _load_yaml(K3S_DIR / "service.yaml")
    cronjob = _load_yaml(K3S_DIR / "market-data-collection-cronjob.yaml")
    deployment_pod = deployment["spec"]["template"]["spec"]
    deployment_container = deployment_pod["containers"][0]
    cron_spec = cronjob["spec"]
    cron_pod = cron_spec["jobTemplate"]["spec"]["template"]["spec"]
    cron_container = cron_pod["containers"][0]

    assert "market-data-collection-cronjob.yaml" in kustomization["resources"]
    assert cron_spec["schedule"] == "30 16 * * 1-5"
    assert cron_spec["timeZone"] == "Asia/Shanghai"
    assert cron_spec["concurrencyPolicy"] == "Forbid"
    assert cron_spec["jobTemplate"]["spec"]["backoffLimit"] == 0
    assert cron_spec["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 3600
    assert cron_container["image"] == deployment_container["image"]
    assert cron_pod["volumes"][0]["persistentVolumeClaim"]["claimName"] == deployment_pod["volumes"][0]["persistentVolumeClaim"]["claimName"]
    assert cron_container["command"][-2:] == ["snapshots", "scheduled-refresh"]
    assert cron_pod["automountServiceAccountToken"] is False
    assert cron_pod["securityContext"]["runAsNonRoot"] is True
    assert cron_container["securityContext"]["readOnlyRootFilesystem"] is True
    assert cron_container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert _environment(cron_container) == _environment(deployment_container)
    assert any(
        cronjob["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"].get(key) != value
        for key, value in service["spec"]["selector"].items()
    )


def test_helm_values_define_enabled_configurable_scheduled_collection() -> None:
    chart = _load_yaml(CHART_DIR / "Chart.yaml")
    values = _load_yaml(CHART_DIR / "values.yaml")
    scheduled = values["marketEnvironment"]["scheduledCollection"]

    assert chart["kubeVersion"] == ">=1.26.0-0"
    assert scheduled["enabled"] is True
    assert scheduled["suspend"] is False
    assert scheduled["schedule"] == "30 16 * * 1-5"
    assert scheduled["timeZone"] == "Asia/Shanghai"
    assert scheduled["startingDeadlineSeconds"] == 1800
    assert scheduled["activeDeadlineSeconds"] == 3600


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_helm_default_render_matches_dashboard_image_pvc_and_security() -> None:
    documents = _render_helm()
    deployment = _resource(documents, "Deployment")
    service = _resource(documents, "Service")
    cronjob = _resource(documents, "CronJob")
    deployment_pod = deployment["spec"]["template"]["spec"]
    deployment_container = deployment_pod["containers"][0]
    cron_pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    cron_container = cron_pod["containers"][0]

    assert cronjob["spec"]["schedule"] == "30 16 * * 1-5"
    assert cronjob["spec"]["timeZone"] == "Asia/Shanghai"
    assert cronjob["spec"]["suspend"] is False
    assert cronjob["spec"]["concurrencyPolicy"] == "Forbid"
    assert cronjob["spec"]["jobTemplate"]["spec"]["backoffLimit"] == 0
    assert cron_container["image"] == deployment_container["image"]
    assert cron_pod["volumes"][0]["persistentVolumeClaim"]["claimName"] == deployment_pod["volumes"][0]["persistentVolumeClaim"]["claimName"]
    assert cron_pod["automountServiceAccountToken"] is False
    assert cron_pod["securityContext"]["runAsNonRoot"] is True
    assert cron_container["securityContext"]["readOnlyRootFilesystem"] is True
    assert _environment(cron_container) == _environment(deployment_container)
    cron_labels = cronjob["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"]
    assert any(cron_labels.get(key) != value for key, value in service["spec"]["selector"].items())


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_helm_render_supports_disabled_suspended_and_custom_schedule() -> None:
    disabled = _render_helm("--set", "marketEnvironment.scheduledCollection.enabled=false")
    custom = _render_helm(
        "--set",
        "marketEnvironment.scheduledCollection.suspend=true",
        "--set-string",
        "marketEnvironment.scheduledCollection.schedule=15 17 * * 1-5",
        "--set-string",
        "marketEnvironment.scheduledCollection.timeZone=Etc/UTC",
    )

    assert all(document.get("kind") != "CronJob" for document in disabled)
    cronjob = _resource(custom, "CronJob")
    assert cronjob["spec"]["suspend"] is True
    assert cronjob["spec"]["schedule"] == "15 17 * * 1-5"
    assert cronjob["spec"]["timeZone"] == "Etc/UTC"


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_helm_render_supports_node_port_on_kubernetes_126() -> None:
    documents = _render_helm(
        "--kube-version",
        "1.26.6",
        "--set",
        "marketEnvironment.scheduledCollection.enabled=false",
        "--set",
        "ingress.enabled=false",
        "--set",
        "service.type=NodePort",
        "--set",
        "service.nodePort=32001",
    )

    service = _resource(documents, "Service")
    assert service["spec"]["type"] == "NodePort"
    assert service["spec"]["ports"][0]["nodePort"] == 32001


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_truenas_direct_access_values_preserve_runtime_and_storage_invariants() -> None:
    documents = _render_helm(
        "--kube-version",
        "1.26.6",
        "--values",
        str(TRUENAS_DIRECT_ACCESS_VALUES),
    )
    deployment = _resource(documents, "Deployment")
    service = _resource(documents, "Service")
    pod = deployment["spec"]["template"]["spec"]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    manual_refresh = [
        item for item in container["env"] if item["name"] == "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED"
    ]

    assert deployment["spec"]["replicas"] == 1
    assert container["image"] == "localhost/a-stock-market-environment:20260905-1904b66"
    assert pod["volumes"][0]["persistentVolumeClaim"]["claimName"] == "a-stock-data"
    assert container["volumeMounts"][0] == {"name": "data", "mountPath": "/data"}
    assert _environment(container)["MARKET_ENVIRONMENT_SNAPSHOT_PATH"] == "/data/snapshots.sqlite3"
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    assert pod["securityContext"]["fsGroup"] == 10001
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert service["spec"]["type"] == "NodePort"
    assert service["spec"]["ports"][0]["nodePort"] == 32001
    assert manual_refresh == [{"name": "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "value": "1"}]
    assert all(document.get("kind") not in {"Ingress", "CronJob", "PersistentVolumeClaim"} for document in documents)


@pytest.mark.skipif(KUBECTL_BINARY is None, reason="kubectl is not installed")
def test_kubectl_kustomize_renders_one_data_collection_cronjob() -> None:
    completed = subprocess.run(
        [str(KUBECTL_BINARY), "kustomize", str(K3S_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    documents = [document for document in yaml.safe_load_all(completed.stdout) if document]
    cronjobs = [document for document in documents if document.get("kind") == "CronJob"]

    assert len(cronjobs) == 1
    assert cronjobs[0]["metadata"]["name"] == "market-data-collection"
